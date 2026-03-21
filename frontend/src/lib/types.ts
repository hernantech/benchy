export type RunStatus =
  | "queued"
  | "running"
  | "passed"
  | "failed"
  | "error"
  | "cancelled";

export interface Run {
  id: string;
  status: RunStatus;
  goal: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  device_id: string | null;
  trigger_type: "manual" | "github_pr" | "agent";
  trigger_ref: string | null;
}

export interface RunStep {
  id: string;
  run_id: string;
  seq: number;
  command_type: string;
  args: Record<string, unknown>;
  status: "queued" | "running" | "succeeded" | "failed";
  result: Record<string, unknown> | null;
  artifact_url: string | null;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
}

export interface Measurement {
  id: string;
  run_id: string;
  name: string;
  value: number;
  unit: string;
  tags: Record<string, string>;
  created_at: string;
}

export interface Diagnosis {
  id: string;
  run_id: string;
  model: string;
  summary: string;
  root_cause: string | null;
  confidence: number | null;
  suggested_fix: Record<string, unknown> | null;
  created_at: string;
}

export interface WaveformData {
  time: number[];
  ch1: number[];
  ch2?: number[];
  sample_rate: number;
  timebase: string;
  v_div_ch1: string;
  v_div_ch2?: string;
}

export interface InstrumentStatus {
  id: string;
  type: "scope" | "psu" | "dut" | "fixture";
  name: string;
  connected: boolean;
  details: Record<string, unknown>;
}
