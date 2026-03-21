/**
 * Client for the RPi hardware runner HTTP API.
 * The runner URL is set via RUNNER_URL env var (server-side only).
 */

const RUNNER_URL = process.env.RUNNER_URL || "http://localhost:8000";

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
    throw new Error(`Runner error ${res.status}: ${await res.text()}`);
  }

  return res.json();
}

// ── Convenience wrappers ──────────────────────────────────────

export async function setPsu(voltage: number, currentLimit: number) {
  return runnerCall("/psu/set", { voltage, current_limit: currentLimit });
}

export async function getPsuTelemetry() {
  return runnerCall("/psu/telemetry");
}

export async function captureScope(
  channel: number = 1,
  sampleRate: number = 1_000_000,
  duration: number = 0.01
) {
  return runnerCall("/scope/capture", {
    channel,
    sample_rate: sampleRate,
    duration,
  });
}

export async function sendDutCommand(cmd: Record<string, unknown>) {
  return runnerCall("/dut/command", cmd);
}

export async function sendFixtureCommand(cmd: Record<string, unknown>) {
  return runnerCall("/fixture/command", cmd);
}

export async function getInstruments() {
  return runnerCall("/instruments");
}
