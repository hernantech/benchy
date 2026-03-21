/**
 * Client for the RPi hardware runner HTTP API.
 * Runs on Pi 5, reachable via Tailscale at RUNNER_URL.
 * All calls are server-side only (API routes).
 */

const RUNNER_URL = process.env.RUNNER_URL || "http://benchagent-pi:8420";

export async function runnerCall(
  endpoint: string,
  body?: Record<string, unknown>
): Promise<Record<string, unknown>> {
  const res = await fetch(`${RUNNER_URL}${endpoint}`, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Runner error ${res.status}: ${text}`);
  }

  return res.json();
}

// ── PSU ─────────────────────────────────────────────────────────

export async function setPsu(
  voltage: number,
  currentLimit: number,
  output: boolean = true
) {
  return runnerCall("/psu/configure", {
    voltage,
    current_limit: currentLimit,
    output,
  });
}

export async function getPsuState() {
  return runnerCall("/psu/state");
}

export async function psuOff() {
  return runnerCall("/psu/off");
}

export async function sweepVoltage(
  start: number,
  stop: number,
  step: number,
  dwell: number = 0.5
) {
  return runnerCall("/psu/sweep", { start, stop, step, dwell });
}

// ── Scope ───────────────────────────────────────────────────────

export async function captureScope(
  channel: number = 0,
  sampleRate: number = 1_000_000,
  duration: number = 0.01,
  vRange: number = 5.0,
  triggerLevel: number = 1.5
) {
  const samples = Math.floor(sampleRate * duration);
  return runnerCall("/scope/capture", {
    channel,
    v_range: vRange,
    samples,
    sample_rate: sampleRate,
    trigger_level: triggerLevel,
  });
}

export async function scopeMeasure(
  channel: number = 0,
  measurement: string = "dc",
  vRange: number = 5.0
) {
  return runnerCall("/scope/measure", { channel, measurement, v_range: vRange });
}

export async function scopePulseWidth(
  channel: number = 0,
  triggerLevel: number = 1.5,
  vRange: number = 5.0,
  sampleRate: number = 10_000_000
) {
  return runnerCall("/scope/pulse_width", {
    channel,
    trigger_level: triggerLevel,
    v_range: vRange,
    sample_rate: sampleRate,
  });
}

export async function scopeSignalIntegrity(
  channel: number = 0,
  sampleRate: number = 10_000_000,
  vRange: number = 5.0
) {
  return runnerCall("/scope/signal_integrity", {
    channel,
    samples: 8192,
    sample_rate: sampleRate,
    v_range: vRange,
  });
}

// ── ESP32 ───────────────────────────────────────────────────────

export async function sendDutCommand(cmd: Record<string, unknown>) {
  return runnerCall("/esp32/a/serial/send", {
    command: JSON.stringify(cmd),
  });
}

export async function sendFixtureCommand(cmd: Record<string, unknown>) {
  return runnerCall("/esp32/b/serial/send", {
    command: JSON.stringify(cmd),
  });
}

export async function resetDut(holdMs: number = 100) {
  return runnerCall("/esp32/a/reset");
}

export async function readDutSerial(timeoutMs: number = 3000) {
  return runnerCall("/esp32/a/serial/read", { timeout_ms: timeoutMs });
}

// ── Protocol ────────────────────────────────────────────────────

export async function captureUart(
  rxPin: number = 0,
  baud: number = 115200,
  durationMs: number = 3000
) {
  return runnerCall("/uart/capture", {
    rx_pin: rxPin,
    baud,
    duration_ms: durationMs,
  });
}

// ── Compound ────────────────────────────────────────────────────

export async function runDebug(params: {
  psu_voltage?: number;
  psu_current_limit?: number;
  scope_channel?: number;
  scope_v_range?: number;
  scope_samples?: number;
  scope_sample_rate?: number;
  scope_trigger_level?: number;
  uart_rx_pin?: number;
  uart_baud?: number;
  capture_duration_ms?: number;
  reset_before?: boolean;
}) {
  return runnerCall("/run/debug", params);
}

export async function runBenchmark(params: {
  kernel: string;
  iterations?: number;
  scope_channel?: number;
  scope_trigger_level?: number;
  measure_power?: boolean;
}) {
  return runnerCall("/run/benchmark", params);
}

// ── Health & Discovery ──────────────────────────────────────────

export async function getHealth() {
  return runnerCall("/health");
}

export async function getCapabilities() {
  return runnerCall("/capabilities");
}

export async function getArtifactUrl(filename: string) {
  return `${RUNNER_URL}/artifacts/${filename}`;
}

// ── Camera ──────────────────────────────────────────────────────

export async function cameraSnapshot() {
  return runnerCall("/camera/snapshot");
}

export async function cameraAnalyze(prompt: string, model: string = "gemini-3.1-flash-lite-preview") {
  return runnerCall("/camera/analyze", { prompt, model });
}

export async function cameraStatus() {
  return runnerCall("/camera/status");
}
