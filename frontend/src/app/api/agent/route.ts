import { NextResponse } from "next/server";
import { google } from "@ai-sdk/google";
import { generateText, tool, stepCountIs } from "ai";
import { z } from "zod";

export async function POST(req: Request) {
  try {
    const { messages } = await req.json();

    const result = await generateText({
      model: google("gemini-2.0-flash"),
      system: `You are Benchy, an AI hardware test agent. You control real lab instruments to test, diagnose, and fix hardware issues on ESP32-S3 development boards.

Available instruments:
- DPS-150 Power Supply (0-30V, 0-5.5A) — set voltage, current limit, sweep
- Digilent Analog Discovery — oscilloscope (2ch), waveform generator, logic analyzer, protocol decoders (I2C/SPI/UART)
- ESP32-S3 DUT board — configurable via JSON commands (PWM, I2C, UART, CAN, GPIO, ADC, WiFi)
- ESP32-S3 Fixture board — I2C slave, DUT reset control, load injection, UART relay

When the user describes a test, you should:
1. Plan the experiment steps
2. Execute them using tools (set_psu, capture_scope, dut_command, fixture_command)
3. Analyze the results (especially waveform data)
4. Report findings with specific measurements
5. If there's a failure, diagnose the root cause and suggest fixes

Be concise and technical. Report measurements with units.`,
      messages,
      tools: {
        set_psu: tool({
          description: "Set the DPS-150 power supply voltage and current limit",
          inputSchema: z.object({
            voltage: z.number().min(0).max(30).describe("Output voltage in volts"),
            current_limit: z.number().min(0).max(5.5).describe("Current limit in amps"),
          }),
          execute: async ({ voltage, current_limit }) => {
            console.log(`[tool] set_psu: ${voltage}V, ${current_limit}A`);
            return { ok: true, voltage, current: 0.042, mode: "CV" };
          },
        }),
        capture_scope: tool({
          description: "Capture a waveform from the Analog Discovery oscilloscope",
          inputSchema: z.object({
            channel: z.number().min(1).max(2).describe("Scope channel (1 or 2)"),
            sample_rate: z.number().default(1000000).describe("Sample rate in Hz"),
            duration: z.number().default(0.01).describe("Capture duration in seconds"),
          }),
          execute: async ({ channel, sample_rate, duration }) => {
            console.log(`[tool] capture_scope: ch${channel}, ${sample_rate}Hz, ${duration}s`);
            return {
              ok: true,
              channel,
              points: Math.floor(sample_rate * duration),
              v_min: 2.41,
              v_max: 3.35,
              v_pp: 0.94,
              v_mean: 3.28,
              freq_detected: null,
            };
          },
        }),
        dut_command: tool({
          description: "Send a JSON command to the ESP32-S3 DUT board",
          inputSchema: z.object({
            cmd: z.string().describe("Command name (e.g., pwm, i2c_init, wifi_connect)"),
            args: z.record(z.string(), z.unknown()).optional().describe("Command arguments"),
          }),
          execute: async ({ cmd, args }) => {
            console.log(`[tool] dut_command: ${cmd}`, args);
            return { ok: true, cmd, ...(args || {}) };
          },
        }),
        fixture_command: tool({
          description: "Send a JSON command to the ESP32-S3 fixture board",
          inputSchema: z.object({
            cmd: z.string().describe("Command name (e.g., reset_dut, i2c_slave_init, load)"),
            args: z.record(z.string(), z.unknown()).optional().describe("Command arguments"),
          }),
          execute: async ({ cmd, args }) => {
            console.log(`[tool] fixture_command: ${cmd}`, args);
            return { ok: true, cmd, ...(args || {}) };
          },
        }),
        sweep_voltage: tool({
          description: "Sweep PSU voltage and capture measurements at each step",
          inputSchema: z.object({
            start: z.number().describe("Start voltage"),
            stop: z.number().describe("Stop voltage"),
            step: z.number().describe("Voltage step size"),
            dwell: z.number().default(2.0).describe("Dwell time per step in seconds"),
          }),
          execute: async ({ start, stop, step, dwell }) => {
            console.log(`[tool] sweep_voltage: ${start}V → ${stop}V, step=${step}, dwell=${dwell}s`);
            return {
              ok: true,
              points: Math.abs(Math.floor((stop - start) / step)) + 1,
              brownout_voltage: 2.8,
              reset_detected: true,
              min_stable_voltage: 2.9,
            };
          },
        }),
      },
      stopWhen: stepCountIs(10),
    });

    console.log(`[agent] completed: ${result.steps.length} steps, ${result.text.length} chars`);

    return NextResponse.json({
      text: result.text,
      toolCalls: result.steps
        .flatMap((s) => s.toolCalls)
        .map((tc) => ({
          name: tc.toolName,
          args: "input" in tc ? tc.input : {},
          result: JSON.stringify(tc),
        })),
    });
  } catch (err) {
    console.error("[agent] error:", err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Agent failed" },
      { status: 500 }
    );
  }
}
