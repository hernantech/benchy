import type { Run, RunStep, Measurement, Diagnosis } from "./types";

export const MOCK_RUNS: Run[] = [
  {
    id: "run-001",
    status: "failed",
    goal: "Boot stress test — sweep 3.6V to 2.5V, detect brownout threshold",
    created_at: "2026-03-21T09:15:00Z",
    started_at: "2026-03-21T09:15:02Z",
    finished_at: "2026-03-21T09:15:38Z",
    device_id: "bench-01",
    trigger_type: "agent",
    trigger_ref: null,
  },
  {
    id: "run-002",
    status: "passed",
    goal: "PWM verification — 38kHz, 33% duty on GPIO4",
    created_at: "2026-03-21T09:20:00Z",
    started_at: "2026-03-21T09:20:01Z",
    finished_at: "2026-03-21T09:20:12Z",
    device_id: "bench-01",
    trigger_type: "manual",
    trigger_ref: null,
  },
  {
    id: "run-003",
    status: "running",
    goal: "I2C signal integrity — 400kHz between DUT and fixture",
    created_at: "2026-03-21T09:25:00Z",
    started_at: "2026-03-21T09:25:01Z",
    finished_at: null,
    device_id: "bench-01",
    trigger_type: "agent",
    trigger_ref: null,
  },
];

export const MOCK_STEPS: RunStep[] = [
  {
    id: "step-1",
    run_id: "run-001",
    seq: 1,
    command_type: "set_psu",
    args: { voltage: 3.6, current_limit: 0.5 },
    status: "succeeded",
    result: { voltage: 3.6, current: 0.042 },
    artifact_url: null,
    started_at: "2026-03-21T09:15:02Z",
    completed_at: "2026-03-21T09:15:03Z",
    error: null,
  },
  {
    id: "step-2",
    run_id: "run-001",
    seq: 2,
    command_type: "capture_scope",
    args: { channel: 1, sample_rate: 1000000, duration: 0.01 },
    status: "succeeded",
    result: { v_min: 3.58, v_max: 3.62, v_pp: 0.04 },
    artifact_url: "/mock-waveform.png",
    started_at: "2026-03-21T09:15:03Z",
    completed_at: "2026-03-21T09:15:05Z",
    error: null,
  },
  {
    id: "step-3",
    run_id: "run-001",
    seq: 3,
    command_type: "sweep_voltage",
    args: { start: 3.6, stop: 2.5, step: -0.1, dwell: 2.0 },
    status: "succeeded",
    result: { brownout_voltage: 2.8, reset_detected: true },
    artifact_url: null,
    started_at: "2026-03-21T09:15:05Z",
    completed_at: "2026-03-21T09:15:30Z",
    error: null,
  },
  {
    id: "step-4",
    run_id: "run-001",
    seq: 4,
    command_type: "analyze",
    args: {},
    status: "failed",
    result: null,
    artifact_url: null,
    started_at: "2026-03-21T09:15:30Z",
    completed_at: "2026-03-21T09:15:38Z",
    error: "Brownout detected at 2.8V — ESP32 reset during WiFi init",
  },
];

export const MOCK_MEASUREMENTS: Measurement[] = [
  {
    id: "m-1",
    run_id: "run-001",
    name: "v_min",
    value: 2.41,
    unit: "V",
    tags: { rail: "3v3", phase: "wifi_init" },
    created_at: "2026-03-21T09:15:28Z",
  },
  {
    id: "m-2",
    run_id: "run-001",
    name: "i_peak",
    value: 0.342,
    unit: "A",
    tags: { rail: "3v3", phase: "wifi_init" },
    created_at: "2026-03-21T09:15:28Z",
  },
  {
    id: "m-3",
    run_id: "run-001",
    name: "droop_duration",
    value: 3.2,
    unit: "ms",
    tags: { rail: "3v3" },
    created_at: "2026-03-21T09:15:28Z",
  },
  {
    id: "m-4",
    run_id: "run-001",
    name: "brownout_threshold",
    value: 2.8,
    unit: "V",
    tags: {},
    created_at: "2026-03-21T09:15:30Z",
  },
];

export const MOCK_DIAGNOSIS: Diagnosis = {
  id: "d-1",
  run_id: "run-001",
  model: "gemini-3.1-pro",
  summary:
    "Boot fails below 2.9V. During WiFi initialization, current spikes to 342mA causing voltage to droop 400mV below the brownout threshold. The ESP32 resets within 3.2ms of the droop.",
  root_cause:
    "Insufficient current budget for WiFi TX burst at low supply voltage. The DPS-150 current limit of 500mA is adequate, but the 3V3 LDO dropout combined with WiFi peak consumption exceeds available margin below 2.9V input.",
  confidence: 0.92,
  suggested_fix: {
    action: "set_psu",
    args: { voltage: 3.3, current_limit: 0.8 },
    description:
      "Increase minimum supply voltage to 3.1V or stagger peripheral initialization to reduce peak current.",
  },
  created_at: "2026-03-21T09:15:38Z",
};

// Generate a fake waveform for demo
export function generateMockWaveform(points: number = 500) {
  const time: number[] = [];
  const ch1: number[] = [];

  for (let i = 0; i < points; i++) {
    const t = (i / points) * 10; // 10ms window
    time.push(t);

    // Normal 3.3V rail with a droop event at t=5ms
    let v = 3.3 + Math.random() * 0.02 - 0.01; // 10mV noise
    if (t > 4.8 && t < 5.5) {
      // WiFi init current spike causes droop
      const droopCenter = 5.15;
      const droopDepth = 0.9;
      const distance = Math.abs(t - droopCenter);
      v -= droopDepth * Math.exp(-(distance * distance) * 20);
    }
    ch1.push(Math.round(v * 1000) / 1000);
  }

  return { time, ch1, sample_rate: 50000, timebase: "1ms/div", v_div_ch1: "500mV/div" };
}
