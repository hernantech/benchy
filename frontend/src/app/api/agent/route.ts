import { NextResponse } from "next/server";
import { google } from "@ai-sdk/google";
import { generateText, tool, stepCountIs } from "ai";
import { z } from "zod";
import { readFileSync } from "fs";
import { join } from "path";
import {
  runnerCall,
  setPsu,
  captureScope,
  scopePulseWidth,
  scopeSignalIntegrity,
  sweepVoltage,
  sendDutCommand,
  sendFixtureCommand,
  runDebug,
  runBenchmark,
  psuOff,
  getHealth,
  getArtifactUrl,
  getCapabilities,
} from "@/lib/runner";

const RUNNER_URL = process.env.RUNNER_URL || "http://benchagent-pi:8420";

// Load wiring reference docs at startup (not per-request)
let WIRING_CHEATSHEET = "";
let FULL_WIRING_REFERENCE = "";
let AD_PINOUT_REFERENCE = "";

function tryLoadDoc(filename: string): string {
  const paths = [
    join(process.cwd(), "..", "docs", filename),
    join(process.cwd(), "docs", filename),
  ];
  for (const p of paths) {
    try { return readFileSync(p, "utf-8"); } catch { /* next */ }
  }
  return "";
}

WIRING_CHEATSHEET = tryLoadDoc("WIRING_CHEATSHEET.md");
FULL_WIRING_REFERENCE = tryLoadDoc("ESP32-S3-DevKitC-1-U-WIRING-REFERENCE.md");
AD_PINOUT_REFERENCE = tryLoadDoc("ANALOG_DISCOVERY_PINOUT.md");

if (!WIRING_CHEATSHEET) {
  console.warn("[agent] Wiring docs not found — agent will have limited wiring guidance");
}

export async function POST(req: Request) {
  try {
    const { messages } = await req.json();

    const result = await generateText({
      model: google("gemini-3.1-pro-preview"),
      system: `You are Benchy, an AI hardware test agent. You control real lab instruments to test, diagnose, and fix hardware issues on ESP32-S3 development boards.

## Architecture
All instruments are connected to a Raspberry Pi 5 ("bench runner") via USB.
You control them through HTTP API calls to the Pi worker.
A phone camera streams video directly to the Pi over Tailscale (not through this server).
When you call camera_analyze, the Pi sends its latest camera frame to Gemini vision.

## Instruments (all on the Pi)
- DPS-150 Power Supply (0-30V, 0-5.5A) — set voltage, current limit, sweep
- Digilent Analog Discovery — oscilloscope (2ch, 0-indexed), waveform generator, logic analyzer, protocol decoders (I2C/SPI/UART)
- ESP32-S3 DUT board — has configurable test-bed firmware accepting JSON commands (PWM, I2C, UART, CAN, GPIO, ADC, WiFi, benchmark kernels)
- ESP32-S3 Fixture board — I2C slave, DUT reset control, load injection, UART relay
- Phone camera — streams to Pi over Tailscale; use camera_status to check, camera_analyze to see the bench

## Two Modes of Operation

### Mode 1: Runtime Configuration (fast, no compile)
The DUT has pre-flashed test-bed firmware that accepts JSON commands over serial.
Use dut_command to configure peripherals on the fly: PWM, I2C, UART, CAN, GPIO, ADC, WiFi.
Use run_benchmark to run pre-compiled DSP kernels (baseline, fir_naive, fir_esp_dsp, optimized).
This is instant — no compilation needed.

### Mode 2: Custom Firmware Generation (when the user wants NEW firmware)
You CAN write, compile, and flash completely new firmware to the ESP32-S3.
Use the generate_firmware tool to trigger the firmware pipeline:
1. Gemini 3.1 Pro architects the firmware (reads docs, decomposes into subtasks)
2. Gemini Flash Lite workers generate code files in parallel
3. Pro stitches everything together, writes main.cpp, verifies correctness
4. PlatformIO compiles on the Pi — if it fails, Pro diagnoses errors and Flash Lite fixes them (up to 3 attempts)
5. Firmware is flashed to the DUT and benchmarked with real instruments

Use Mode 2 when:
- The user asks you to "write firmware" or "create a driver"
- The user wants custom signal processing, protocol handling, or control logic
- The user wants ISA-optimized code for the ESP32-S3 Xtensa LX7
- The pre-flashed test-bed firmware can't do what's needed

## Workflow
1. If the user needs help with wiring, use camera_analyze to see the bench and guide them. You can also use the wiring_reference tool for detailed pin information.
2. Decide: use Mode 1 (runtime config) or Mode 2 (generate firmware) based on what the user asks
3. Plan the experiment steps
4. Execute using tools (set_psu, capture_scope, dut_command, generate_firmware, etc.)
5. Analyze results (waveform stats, UART logs, scope charts)
6. Report findings with specific measurements and units
7. If failure detected, use the RCA pipeline to diagnose root cause

## Root Cause Analysis (RCA) Workflow
When diagnosing hardware failures, use the RCA analysis pipeline:
1. Capture measurement data (scope, PSU, serial)
2. Call analyze_rca_start to create a session
3. Call analyze_rca with measurement data — you'll get structured metrics and ranked hypotheses
4. Review the hypotheses and their verification steps
5. Either: fix firmware, instruct user on hardware fix, or probe more test points
6. After each fix or new measurement, call analyze_rca again to update the analysis
7. When confident in root cause, call analyze_rca_report to generate the final report

The RCA tool gives you EE analysis you can't do yourself (FFT, rise time, threshold comparisons).
Use it instead of guessing from raw waveform numbers.

## Safety — User Confirmation Gate
Before ANY action that energizes hardware or changes physical state, you MUST:
1. Tell the user exactly what you're about to do and what should be connected
2. Wait for the user to confirm the setup is correct
3. Only then execute the instrument commands
NEVER set PSU voltage or enable output without user confirmation.
The PSU feeds VIN (regulator input) — the LDO converts to 3.3V. NEVER instruct connecting PSU directly to a 3.3V rail.

## Rules
- Scope channels: 0-indexed (0=CH1, 1=CH2)
- Always enable PSU output when setting voltage (output=true)
- DUT commands are flat JSON: {"cmd":"pwm","pin":4,"freq":1000,"duty":50}
- ESP32-S3 is 3.3V logic — NEVER set PSU above 3.6V when powering 3V3 pin directly
- Safety clamps: max 5.5V, max 1.0A (enforced by Pi worker)

## Quick Wiring Reference
${WIRING_CHEATSHEET || "(wiring docs not loaded)"}

Be concise and technical. Report measurements with units. When guiding wiring, reference specific header pins (e.g., "connect to J1-4 which is GPIO4").`,
      messages,
      tools: {
        set_psu: tool({
          description:
            "Set the DPS-150 power supply voltage and current limit. Enables output by default.",
          inputSchema: z.object({
            voltage: z
              .number()
              .min(0)
              .max(5.5)
              .describe("Output voltage in volts (max 5.5V for safety)"),
            current_limit: z
              .number()
              .min(0)
              .max(1.0)
              .describe("Current limit in amps (max 1.0A for safety)"),
            output: z
              .boolean()
              .default(true)
              .describe("Enable output (default true)"),
          }),
          execute: async ({ voltage, current_limit, output }) => {
            const res = await setPsu(voltage, current_limit, output);
            return res;
          },
        }),

        psu_off: tool({
          description: "Immediately disable the power supply output (safety)",
          inputSchema: z.object({}),
          execute: async () => {
            return await psuOff();
          },
        }),

        capture_scope: tool({
          description:
            "Capture a waveform from the Analog Discovery oscilloscope. Returns stats and a chart image URL.",
          inputSchema: z.object({
            channel: z
              .number()
              .min(0)
              .max(1)
              .default(0)
              .describe("Scope channel (0=CH1, 1=CH2)"),
            sample_rate: z
              .number()
              .default(1000000)
              .describe("Sample rate in Hz"),
            duration: z
              .number()
              .default(0.01)
              .describe("Capture duration in seconds"),
            v_range: z
              .number()
              .default(5.0)
              .describe("Voltage range in volts"),
            trigger_level: z
              .number()
              .default(1.5)
              .describe("Trigger level in volts"),
          }),
          execute: async ({
            channel,
            sample_rate,
            duration,
            v_range,
            trigger_level,
          }) => {
            const samples = Math.floor(sample_rate * duration);
            const res = await runnerCall("/scope/capture", {
              channel,
              v_range,
              samples,
              sample_rate,
              trigger_level,
            });
            // Convert chart_url to full URL for Gemini vision
            if (res.chart_url) {
              res.chart_full_url = `${RUNNER_URL}${res.chart_url}`;
            }
            return res;
          },
        }),

        measure_pulse_width: tool({
          description:
            "Capture a GPIO timing pulse and measure its width. Used for benchmarking execution time.",
          inputSchema: z.object({
            channel: z
              .number()
              .min(0)
              .max(1)
              .default(0)
              .describe("Scope channel (0=CH1, 1=CH2)"),
            trigger_level: z
              .number()
              .default(1.5)
              .describe("Trigger level in volts"),
          }),
          execute: async ({ channel, trigger_level }) => {
            const res = await scopePulseWidth(channel, trigger_level);
            if (res.chart_url) {
              res.chart_full_url = `${RUNNER_URL}${res.chart_url}`;
            }
            return res;
          },
        }),

        signal_integrity: tool({
          description:
            "Analyze signal integrity: rise/fall time, overshoot, undershoot. Use for I2C/SPI bus quality checks.",
          inputSchema: z.object({
            channel: z
              .number()
              .min(0)
              .max(1)
              .default(0)
              .describe("Scope channel"),
            sample_rate: z
              .number()
              .default(10000000)
              .describe("Sample rate (use 10MHz+ for signal integrity)"),
          }),
          execute: async ({ channel, sample_rate }) => {
            const res = await scopeSignalIntegrity(channel, sample_rate);
            if (res.chart_url) {
              res.chart_full_url = `${RUNNER_URL}${res.chart_url}`;
            }
            return res;
          },
        }),

        sweep_voltage: tool({
          description:
            "Sweep PSU voltage from start to stop, measuring at each step. Use to find brownout thresholds.",
          inputSchema: z.object({
            start: z.number().describe("Start voltage"),
            stop: z.number().describe("Stop voltage"),
            step: z
              .number()
              .describe("Voltage step size (use negative for downward sweep)"),
            dwell: z
              .number()
              .default(0.5)
              .describe("Dwell time per step in seconds"),
          }),
          execute: async ({ start, stop, step, dwell }) => {
            return await sweepVoltage(start, stop, step, dwell);
          },
        }),

        dut_command: tool({
          description: `Send a JSON command to the ESP32-S3 DUT board. Commands are flat JSON objects.
Examples:
  {"cmd":"pwm","pin":4,"freq":1000,"duty":50}
  {"cmd":"i2c_init","sda":8,"scl":9,"freq":400000}
  {"cmd":"i2c_scan"}
  {"cmd":"wifi_connect","ssid":"test","pass":"password"}
  {"cmd":"adc_read","pin":1,"samples":10}
  {"cmd":"can_init","tx":5,"rx":6,"baud":500,"mode":"no_ack"}
  {"cmd":"status"}`,
          inputSchema: z.object({
            cmd: z
              .string()
              .describe("Command name (e.g., pwm, i2c_init, wifi_connect)"),
            pin: z.number().optional().describe("Pin number"),
            freq: z.number().optional().describe("Frequency in Hz"),
            duty: z.number().optional().describe("Duty cycle 0-100%"),
            sda: z.number().optional().describe("I2C SDA pin"),
            scl: z.number().optional().describe("I2C SCL pin"),
            addr: z.number().optional().describe("I2C address"),
            baud: z.number().optional().describe("Baud rate / CAN kbps"),
            ssid: z.string().optional().describe("WiFi SSID"),
            pass: z.string().optional().describe("WiFi password"),
            tx: z.number().optional().describe("TX pin"),
            rx: z.number().optional().describe("RX pin"),
            mode: z.string().optional().describe("Mode string"),
            value: z.number().optional().describe("GPIO value"),
            samples: z.number().optional().describe("ADC sample count"),
            data: z.array(z.number()).optional().describe("Data bytes"),
            len: z.number().optional().describe("Read length"),
            id: z.number().optional().describe("CAN message ID"),
            timeout: z.number().optional().describe("Timeout in ms"),
            text: z.string().optional().describe("UART text to send"),
          }),
          execute: async (args) => {
            // Build flat command object for ESP32 firmware
            const cmd: Record<string, unknown> = {};
            for (const [k, v] of Object.entries(args)) {
              if (v !== undefined) cmd[k] = v;
            }
            return await sendDutCommand(cmd);
          },
        }),

        fixture_command: tool({
          description: `Send a JSON command to the ESP32-S3 fixture board.
Examples:
  {"cmd":"reset_dut","hold_ms":100}
  {"cmd":"i2c_slave_init","addr":85}
  {"cmd":"i2c_slave_set_resp","data":[66,67,68]}
  {"cmd":"i2c_slave_set_mode","mode":"delay","delay_us":500}
  {"cmd":"load","pin":4,"duty":50}
  {"cmd":"can_init","mode":"no_ack","baud":500}`,
          inputSchema: z.object({
            cmd: z
              .string()
              .describe("Command name (e.g., reset_dut, i2c_slave_init, load)"),
            hold_ms: z.number().optional(),
            addr: z.number().optional(),
            data: z.array(z.number()).optional(),
            mode: z.string().optional(),
            delay_us: z.number().optional(),
            pin: z.number().optional(),
            duty: z.number().optional(),
            freq: z.number().optional(),
            baud: z.number().optional(),
            tx: z.number().optional(),
            rx: z.number().optional(),
          }),
          execute: async (args) => {
            const cmd: Record<string, unknown> = {};
            for (const [k, v] of Object.entries(args)) {
              if (v !== undefined) cmd[k] = v;
            }
            return await sendFixtureCommand(cmd);
          },
        }),

        run_debug: tool({
          description:
            "Execute a full hardware debug cycle: set PSU, reset DUT, capture scope + UART, detect brownout. Returns everything in one call.",
          inputSchema: z.object({
            psu_voltage: z.number().default(3.3).describe("PSU voltage"),
            psu_current_limit: z
              .number()
              .default(0.15)
              .describe("PSU current limit in amps"),
            scope_channel: z.number().default(0).describe("Scope channel"),
            capture_duration_ms: z
              .number()
              .default(3000)
              .describe("How long to capture UART/scope"),
            reset_before: z
              .boolean()
              .default(true)
              .describe("Reset DUT before capture"),
          }),
          execute: async (args) => {
            const res = await runDebug(args);
            // Attach full URLs for artifacts
            const scope = res.scope as Record<string, unknown> | undefined;
            if (scope?.chart_url) {
              scope.chart_full_url = `${RUNNER_URL}${scope.chart_url}`;
            }
            return res;
          },
        }),

        generate_firmware: tool({
          description: `Generate, compile, and flash custom firmware to the ESP32-S3 DUT.
This triggers the full firmware pipeline:
1. Gemini 3.1 Pro architects the firmware (reads your goal + any reference docs/code)
2. Flash Lite workers generate code files in parallel from the spec
3. Pro stitches them together, writes main.cpp, verifies correctness
4. PlatformIO compiles for ESP32-S3 — if it fails, Pro diagnoses and Flash Lite fixes (up to 3 retries)
5. Firmware is flashed to the DUT and tested

Use this when the user wants CUSTOM firmware — not when they just want to configure the existing test-bed firmware via JSON commands.
The pipeline takes 1-3 minutes depending on complexity and compile retries.`,
          inputSchema: z.object({
            goal: z
              .string()
              .describe(
                "What the firmware should do (e.g., 'FIR filter optimized for ESP32-S3 Xtensa LX7 with GPIO timing harness')"
              ),
            source_code: z
              .string()
              .optional()
              .describe(
                "Existing C/C++ code to optimize or build upon (optional)"
              ),
            reference_docs: z
              .string()
              .optional()
              .describe(
                "Reference documentation, datasheets, or API specs (optional)"
              ),
            instructions: z
              .string()
              .optional()
              .describe("Additional instructions for the firmware pipeline"),
          }),
          execute: async ({ goal, source_code, reference_docs, instructions }) => {
            const PIPELINE_URL = process.env.PIPELINE_URL || "http://pipeline:8002";
            try {
              const res = await fetch(`${PIPELINE_URL}/firmware`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  runner_url: RUNNER_URL,
                  goal,
                  source_code: source_code || "",
                  reference_docs: reference_docs || "",
                  instructions: instructions || "",
                }),
              });
              if (!res.ok) {
                return { error: `Pipeline returned ${res.status}: ${await res.text()}` };
              }
              return await res.json();
            } catch (e) {
              return { error: `Failed to reach firmware pipeline: ${e}` };
            }
          },
        }),

        run_benchmark: tool({
          description:
            "Execute a firmware benchmark: select kernel on ESP32, measure execution time via GPIO pulse + scope, measure power via PSU. Works with both pre-flashed test-bed kernels AND newly generated firmware.",
          inputSchema: z.object({
            kernel: z
              .string()
              .describe(
                "Kernel name to run (e.g., baseline, optimized, fir_naive, fir_esp_dsp)"
              ),
            iterations: z
              .number()
              .default(1000)
              .describe("Number of iterations"),
            measure_power: z
              .boolean()
              .default(true)
              .describe("Also measure power consumption"),
          }),
          execute: async (args) => {
            const res = await runBenchmark(args);
            const execution = res.execution as
              | Record<string, unknown>
              | undefined;
            if (execution?.chart_url) {
              execution.chart_full_url = `${RUNNER_URL}${execution.chart_url}`;
            }
            return res;
          },
        }),

        health_check: tool({
          description:
            "Check which instruments are connected (scope, PSU, ESP32 boards)",
          inputSchema: z.object({}),
          execute: async () => {
            return await getHealth();
          },
        }),

        get_capabilities: tool({
          description:
            "Discover all available bench commands with their parameters, types, units, and defaults. Call this first to understand what the bench can do. Returns the full tool catalog with live device connectivity.",
          inputSchema: z.object({}),
          execute: async () => {
            return await getCapabilities();
          },
        }),

        wiring_reference: tool({
          description: `Look up detailed wiring information for the hardware setup.
Two documents available:
1. "esp32" — ESP32-S3-DevKitC-1-U pinout, GPIO safety, header layout, peripheral defaults
2. "ad" or "analog_discovery" — Analog Discovery (original) pinout, wire colors (orange=CH1, blue=CH2, pink=DIO0, etc.), connector layout

Use this when you need:
- Exact GPIO pin numbers and header positions (esp32)
- Wire colors for the Analog Discovery fly-wire cable (ad)
- Which pins are safe vs reserved (esp32)
- How to connect scope/UART/I2C probes (both docs)
- Power supply connection details (both docs)

The quick cheatsheet (with wire colors) is already in your system prompt. Use this tool for the FULL reference.`,
          inputSchema: z.object({
            doc: z
              .enum(["esp32", "ad", "analog_discovery", "all"])
              .default("all")
              .describe("Which reference doc: 'esp32' for the dev board, 'ad' for Analog Discovery, 'all' for both"),
            section: z
              .string()
              .optional()
              .describe(
                "Optional: specific section to look up (e.g., 'pinout', 'power', 'i2c', 'safety', 'scope', 'digital', 'wire color')"
              ),
          }),
          execute: async ({ doc, section }) => {
            // Select which docs to search
            const docs: { name: string; content: string }[] = [];
            if (doc === "esp32" || doc === "all") {
              if (FULL_WIRING_REFERENCE) docs.push({ name: "ESP32-S3 DevKitC-1-U", content: FULL_WIRING_REFERENCE });
            }
            if (doc === "ad" || doc === "analog_discovery" || doc === "all") {
              if (AD_PINOUT_REFERENCE) docs.push({ name: "Analog Discovery (Original)", content: AD_PINOUT_REFERENCE });
            }

            if (docs.length === 0) {
              return { error: "Reference docs not loaded. Use the cheatsheet in the system prompt." };
            }

            if (section) {
              const sectionLower = section.toLowerCase();
              const results: { doc: string; content: string }[] = [];
              for (const d of docs) {
                const lines = d.content.split("\n");
                let capturing = false;
                let result = "";
                let depth = 0;
                for (const line of lines) {
                  if (line.startsWith("#") && line.toLowerCase().includes(sectionLower)) {
                    capturing = true;
                    depth = line.split(" ")[0].length;
                    result += line + "\n";
                  } else if (capturing) {
                    if (line.startsWith("#") && line.split(" ")[0].length <= depth) break;
                    result += line + "\n";
                  }
                }
                if (result) results.push({ doc: d.name, content: result });
              }
              if (results.length > 0) return { section, results };
              return { section, error: `Section '${section}' not found. Try: pinout, power, scope, digital, wire color, safety, i2c, uart` };
            }

            // Return full docs (truncated)
            return {
              documents: docs.map(d => ({
                name: d.name,
                content: d.content.slice(0, 10000),
                truncated: d.content.length > 10000,
              })),
            };
          },
        }),

        camera_snapshot: tool({
          description:
            "Take a photo from the phone camera stream currently pointed at the lab bench. Returns the image URL. Use this before camera_analyze to confirm the camera is working.",
          inputSchema: z.object({}),
          execute: async () => {
            const res = await runnerCall("/camera/snapshot");
            if (res.artifact_url) {
              res.image_url = `${RUNNER_URL}${res.artifact_url}`;
            }
            return res;
          },
        }),

        camera_analyze: tool({
          description: `Analyze the lab bench using the phone camera + Gemini 3.1 Flash Lite vision.
The phone streams video directly to the Pi over Tailscale. This tool grabs the latest frame from the Pi and sends it to Gemini for analysis.
Use this to:
- Verify wiring is correct before running tests ("Are the I2C wires connected between the two ESP32 boards?")
- Identify instruments and boards ("What instruments are on the bench?")
- Check probe placement ("Is the scope probe on the 3V3 rail?")
- Diagnose physical issues ("Why might the ESP32 not be powering on?")
- Guide the user step-by-step through wiring changes ("Now connect the yellow wire from J1-12 to...")
Call camera_status first to check if the phone is streaming.`,
          inputSchema: z.object({
            prompt: z
              .string()
              .describe(
                "What to look for / analyze in the camera image. Be specific."
              ),
          }),
          execute: async ({ prompt }) => {
            const res = await runnerCall("/camera/analyze", {
              prompt,
              model: "gemini-3.1-flash-lite-preview",
            });
            if (res.artifact_url) {
              res.image_url = `${RUNNER_URL}${res.artifact_url}`;
            }
            return res;
          },
        }),

        camera_status: tool({
          description:
            "Check if the phone camera is connected and streaming frames.",
          inputSchema: z.object({}),
          execute: async () => {
            return await runnerCall("/camera/status");
          },
        }),

        analyze_rca_start: tool({
          description:
            "Start a new Root Cause Analysis session for diagnosing a hardware issue. Returns a session_id for subsequent analyze_rca calls.",
          inputSchema: z.object({
            test_goal: z
              .string()
              .describe("What is being tested (e.g., '3.3V rail stability')"),
            test_point: z
              .string()
              .describe(
                "Physical test point name (e.g., 'U3 output pin 5')"
              ),
          }),
          execute: async ({ test_goal, test_point }) => {
            return await runnerCall("/rca/session", { test_goal, test_point });
          },
        }),

        analyze_rca: tool({
          description: `Run Root Cause Analysis on measurement data. Feed in scope waveforms, PSU telemetry, and/or serial logs.
Returns structured metrics with PASS/WARN/FAIL verdicts and ranked hypotheses with evidence chains and verification steps.
Use this AFTER capturing scope/PSU/serial data to diagnose failures. The RCA tool gives you EE analysis you can't do yourself (FFT, rise time, threshold comparisons).`,
          inputSchema: z.object({
            session_id: z.string(),
            waveform_data: z
              .array(z.number())
              .optional()
              .describe("Raw scope samples from capture_scope"),
            sample_rate: z.number().default(1000000),
            expected_voltage: z
              .number()
              .optional()
              .describe("Nominal DC voltage (e.g., 3.3)"),
            max_ripple_mv: z
              .number()
              .optional()
              .describe("Max acceptable ripple in mV"),
            psu_voltage: z
              .number()
              .optional()
              .describe("PSU measured voltage from psu/state"),
            psu_current: z
              .number()
              .optional()
              .describe("PSU measured current from psu/state"),
            serial_log: z
              .string()
              .optional()
              .describe("Serial output from DUT"),
          }),
          execute: async (args) => {
            return await runnerCall("/rca/analyze", args);
          },
        }),

        analyze_rca_report: tool({
          description:
            "Generate the final RCA report for a diagnosis session. Call this when you've identified the root cause or exhausted iterations.",
          inputSchema: z.object({
            session_id: z.string(),
            reason: z
              .string()
              .default("resolved")
              .describe("Resolution reason: resolved, escalated, max_iterations"),
          }),
          execute: async (args) => {
            return await runnerCall("/rca/report", args);
          },
        }),
      },
      stopWhen: stepCountIs(15),
    });

    // Merge tool calls with their results from each step
    const toolCalls = result.steps.flatMap((s) => {
      const resultsMap = new Map(
        (s.toolResults ?? []).map((tr: any) => [tr.toolCallId, tr.result])
      );
      return s.toolCalls.map((tc) => ({
        name: tc.toolName,
        args: "input" in tc ? tc.input : {},
        result: resultsMap.get(tc.toolCallId),
      }));
    });

    return NextResponse.json({
      text: result.text,
      toolCalls,
    });
  } catch (err) {
    console.error("[agent] error:", err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Agent failed" },
      { status: 500 }
    );
  }
}
