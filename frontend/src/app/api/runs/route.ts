import { NextResponse } from "next/server";
import { MOCK_RUNS, MOCK_STEPS, MOCK_MEASUREMENTS, MOCK_DIAGNOSIS } from "@/lib/mock-data";

const RUNNER_URL = process.env.RUNNER_URL || "http://benchagent-pi:8420";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const runId = url.searchParams.get("id");
  const action = url.searchParams.get("action");

  if (action === "instruments") {
    // Fetch live instrument status from the Pi worker
    try {
      const res = await fetch(`${RUNNER_URL}/health`, {
        signal: AbortSignal.timeout(5000),
      });
      if (!res.ok) throw new Error(`Pi worker returned ${res.status}`);
      const health = await res.json();
      const devices = health.devices || {};

      const instruments = [];

      if (devices.ad2) {
        instruments.push({
          id: "ad2",
          type: "scope",
          name: "Digilent Analog Discovery",
          connected: devices.ad2.connected,
          port: devices.ad2.serial ? `SN:${devices.ad2.serial}` : undefined,
          details: {
            channels: 2,
            max_sample_rate: "100 MSa/s",
            bandwidth: "5 MHz",
            features: ["Scope", "Waveform Gen", "Logic Analyzer", "Protocol Decoder", "I2C/SPI/UART"],
          },
        });
      }

      if (devices.psu) {
        instruments.push({
          id: "dps150",
          type: "psu",
          name: devices.psu.model || "FNIRSI DPS-150",
          connected: devices.psu.connected,
          port: devices.psu.connected ? "USB Serial" : undefined,
          details: {
            max_voltage: "30V",
            max_current: "5.5A",
            ...(devices.psu.input_voltage ? { input_voltage: `${devices.psu.input_voltage}V` } : {}),
            features: ["Voltage Sweep", "Current Limit", "OVP/OCP/OPP/OTP", "Telemetry"],
          },
        });
      }

      if (devices.esp32_a) {
        instruments.push({
          id: "dut",
          type: "dut",
          name: "ESP32-S3 DevKitC-1 (DUT)",
          connected: devices.esp32_a.connected,
          port: devices.esp32_a.port,
          details: {
            chip: "ESP32-S3",
            firmware: "benchy-dut v1.0.0",
            peripherals: ["PWM", "I2C", "UART", "CAN/TWAI", "GPIO", "ADC", "WiFi"],
          },
        });
      }

      if (devices.esp32_b) {
        instruments.push({
          id: "fixture",
          type: "fixture",
          name: "ESP32-S3 DevKitC-1 (Fixture)",
          connected: devices.esp32_b.connected,
          port: devices.esp32_b.port,
          details: {
            chip: "ESP32-S3",
            firmware: "benchy-fixture v1.0.0",
            peripherals: ["I2C Slave", "CAN Partner", "DUT Reset", "Load Injection", "UART Relay"],
          },
        });
      }

      // Check camera status
      try {
        const camRes = await fetch(`${RUNNER_URL}/camera/status`, {
          signal: AbortSignal.timeout(3000),
        });
        if (camRes.ok) {
          const cam = await camRes.json();
          instruments.push({
            id: "camera",
            type: "camera",
            name: "Phone Camera (Flutter)",
            connected: cam.connected,
            port: cam.connected ? "WebSocket" : undefined,
            details: {
              streaming: cam.has_frame,
              ...(cam.frame_age_ms != null ? { frame_age_ms: cam.frame_age_ms } : {}),
            },
          });
        }
      } catch {
        // Camera check is optional
      }

      return NextResponse.json({ instruments });
    } catch (e) {
      // Pi worker unreachable — return empty so frontend falls back to mocks
      console.warn("[instruments] Pi worker unreachable:", e);
      return NextResponse.json({ instruments: [] });
    }
  }

  if (runId) {
    const run = MOCK_RUNS.find((r) => r.id === runId);
    if (!run) return NextResponse.json({ error: "Run not found" }, { status: 404 });

    return NextResponse.json({
      run,
      steps: MOCK_STEPS.filter((s) => s.run_id === runId),
      measurements: MOCK_MEASUREMENTS.filter((m) => m.run_id === runId),
      diagnosis: runId === MOCK_DIAGNOSIS.run_id ? MOCK_DIAGNOSIS : null,
    });
  }

  return NextResponse.json({ runs: MOCK_RUNS });
}

export async function POST(req: Request) {
  const body = await req.json();

  const run = {
    id: `run-${Date.now()}`,
    status: "queued" as const,
    goal: body.goal || "Unnamed run",
    created_at: new Date().toISOString(),
    started_at: null,
    finished_at: null,
    device_id: "bench-01",
    trigger_type: body.trigger_type || "manual",
    trigger_ref: body.trigger_ref || null,
  };

  return NextResponse.json({ run }, { status: 201 });
}
