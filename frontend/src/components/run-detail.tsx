"use client";

import type { Run } from "@/lib/types";
import {
  MOCK_STEPS,
  MOCK_MEASUREMENTS,
  MOCK_DIAGNOSIS,
  generateMockWaveform,
} from "@/lib/mock-data";
import { WaveformChart } from "./waveform-chart";

const STATUS_COLORS: Record<string, string> = {
  succeeded: "text-success",
  failed: "text-destructive",
  running: "text-primary",
  queued: "text-warning",
};

const STATUS_DOTS: Record<string, string> = {
  succeeded: "bg-success",
  failed: "bg-destructive",
  running: "bg-primary animate-pulse",
  queued: "bg-warning",
};

export function RunDetail({ run }: { run: Run }) {
  // TODO: replace with Supabase realtime data
  const steps = MOCK_STEPS.filter((s) => s.run_id === run.id);
  const measurements = MOCK_MEASUREMENTS.filter((m) => m.run_id === run.id);
  const diagnosis = run.id === MOCK_DIAGNOSIS.run_id ? MOCK_DIAGNOSIS : null;
  const waveform = generateMockWaveform();

  return (
    <div className="p-6 space-y-6 max-w-5xl">
      {/* Header */}
      <div>
        <div className="flex items-center gap-3 mb-2">
          <h1 className="text-lg font-semibold">{run.goal}</h1>
          <span
            className={`text-xs font-mono uppercase px-2 py-0.5 rounded-sm ${
              run.status === "passed"
                ? "bg-success/15 text-success"
                : run.status === "failed"
                  ? "bg-destructive/15 text-destructive"
                  : run.status === "running"
                    ? "bg-primary/15 text-primary"
                    : "bg-muted text-muted-foreground"
            }`}
          >
            {run.status}
          </span>
        </div>
        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          <span className="font-mono">{run.id}</span>
          <span>&middot;</span>
          <span>{run.device_id || "no device"}</span>
          <span>&middot;</span>
          <span>{run.trigger_type}</span>
          {run.started_at && (
            <>
              <span>&middot;</span>
              <span>{new Date(run.started_at).toLocaleTimeString()}</span>
            </>
          )}
        </div>
      </div>

      {/* Waveform */}
      <WaveformChart
        time={waveform.time}
        ch1={waveform.ch1}
        title="3V3 Rail — Boot Sequence"
        brownoutThreshold={2.44}
      />

      {/* Two-column: Steps + Measurements */}
      <div className="grid grid-cols-2 gap-6">
        {/* Step Timeline */}
        <div className="bg-card rounded-md border border-border p-6">
          <h3 className="text-sm font-medium mb-4 text-muted-foreground">
            Steps
          </h3>
          <div className="space-y-3">
            {steps.map((step) => (
              <div key={step.id} className="flex items-start gap-3">
                <div className="mt-1.5">
                  <div
                    className={`w-2 h-2 rounded-full ${STATUS_DOTS[step.status] || "bg-muted-foreground"}`}
                  />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-mono">
                      {step.command_type}
                    </span>
                    <span
                      className={`text-xs ${STATUS_COLORS[step.status] || "text-muted-foreground"}`}
                    >
                      {step.status}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground truncate mt-0.5">
                    {JSON.stringify(step.args)}
                  </p>
                  {step.error && (
                    <p className="text-xs text-destructive mt-1">
                      {step.error}
                    </p>
                  )}
                </div>
              </div>
            ))}
            {steps.length === 0 && (
              <p className="text-xs text-muted-foreground">
                No steps recorded yet.
              </p>
            )}
          </div>
        </div>

        {/* Measurements */}
        <div className="bg-card rounded-md border border-border p-6">
          <h3 className="text-sm font-medium mb-4 text-muted-foreground">
            Measurements
          </h3>
          <div className="space-y-2">
            {measurements.map((m) => (
              <div
                key={m.id}
                className="flex items-center justify-between py-1 border-b border-border last:border-0"
              >
                <span className="text-sm font-mono">{m.name}</span>
                <span className="text-sm">
                  <span className="font-semibold">{m.value}</span>
                  <span className="text-muted-foreground ml-1">{m.unit}</span>
                </span>
              </div>
            ))}
            {measurements.length === 0 && (
              <p className="text-xs text-muted-foreground">
                No measurements yet.
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Diagnosis */}
      {diagnosis && (
        <div className="bg-card rounded-md border border-border p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-medium text-muted-foreground">
              AI Diagnosis
            </h3>
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono text-muted-foreground">
                {diagnosis.model}
              </span>
              {diagnosis.confidence && (
                <span className="text-xs bg-accent/15 text-accent px-1.5 py-0.5 rounded-sm font-mono">
                  {Math.round(diagnosis.confidence * 100)}%
                </span>
              )}
            </div>
          </div>
          <p className="text-sm leading-relaxed mb-3">{diagnosis.summary}</p>
          {diagnosis.root_cause && (
            <div className="mt-4 pt-4 border-t border-border">
              <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                Root Cause
              </h4>
              <p className="text-sm">{diagnosis.root_cause}</p>
            </div>
          )}
          {diagnosis.suggested_fix && (
            <div className="mt-4 pt-4 border-t border-border">
              <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                Suggested Fix
              </h4>
              <p className="text-sm mb-3">
                {(diagnosis.suggested_fix as { description?: string })
                  .description || JSON.stringify(diagnosis.suggested_fix)}
              </p>
              <button className="bg-primary text-primary-foreground text-sm font-medium px-4 py-2 rounded-md hover:bg-primary/90 transition-colors">
                Apply Fix &amp; Rerun
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
