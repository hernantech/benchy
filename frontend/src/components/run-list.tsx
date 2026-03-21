"use client";

import { MOCK_RUNS } from "@/lib/mock-data";
import type { Run } from "@/lib/types";

const STATUS_STYLES: Record<string, string> = {
  passed: "bg-success/15 text-success",
  failed: "bg-destructive/15 text-destructive",
  running: "bg-primary/15 text-primary",
  queued: "bg-warning/15 text-warning",
  error: "bg-destructive/15 text-destructive",
  cancelled: "bg-muted text-muted-foreground",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`text-[10px] font-mono uppercase px-1.5 py-0.5 rounded-sm ${STATUS_STYLES[status] || "bg-muted text-muted-foreground"}`}
    >
      {status}
    </span>
  );
}

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

interface RunListProps {
  selectedId?: string;
  onSelect: (run: Run) => void;
}

export function RunList({ selectedId, onSelect }: RunListProps) {
  // TODO: replace with Supabase realtime subscription
  const runs = MOCK_RUNS;

  return (
    <div className="flex-1 overflow-auto">
      {runs.map((run) => (
        <button
          key={run.id}
          onClick={() => onSelect(run)}
          className={`w-full text-left px-4 py-3 border-b border-border hover:bg-surface-2 transition-colors ${
            selectedId === run.id ? "bg-surface-2" : ""
          }`}
        >
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-mono text-muted-foreground">
              {run.id}
            </span>
            <StatusBadge status={run.status} />
          </div>
          <p className="text-sm truncate">{run.goal}</p>
          <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
            <span>{run.trigger_type}</span>
            <span>&middot;</span>
            <span>{timeAgo(run.created_at)}</span>
          </div>
        </button>
      ))}

      {runs.length === 0 && (
        <div className="p-8 text-center text-muted-foreground text-sm">
          No runs yet. Start one from the Agent page.
        </div>
      )}
    </div>
  );
}
