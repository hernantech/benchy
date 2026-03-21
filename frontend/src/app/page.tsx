"use client";

import { useState } from "react";
import { RunList } from "@/components/run-list";
import { RunDetail } from "@/components/run-detail";
import { AgentChat } from "@/components/agent-chat";
import type { Run } from "@/lib/types";

export default function HomePage() {
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);

  return (
    <div className="flex h-[calc(100vh-56px)]">
      {/* Left sidebar — run list */}
      <div className="w-72 border-r border-border flex flex-col bg-card shrink-0">
        <div className="p-4 border-b border-border flex items-center justify-between">
          <h2 className="font-semibold text-sm">Test Runs</h2>
        </div>
        <RunList selectedId={selectedRun?.id} onSelect={setSelectedRun} />
      </div>

      {/* Center — run detail */}
      <div className="flex-1 overflow-auto min-w-0">
        {selectedRun ? (
          <RunDetail run={selectedRun} />
        ) : (
          <div className="flex items-center justify-center h-full text-muted-foreground">
            <div className="text-center">
              <div className="text-4xl mb-3 font-mono">&gt;_</div>
              <p className="text-sm">Select a run to view details</p>
            </div>
          </div>
        )}
      </div>

      {/* Right panel — agent chat */}
      <div className="w-[400px] border-l border-border flex flex-col bg-card shrink-0">
        <div className="p-4 border-b border-border">
          <h2 className="font-semibold text-sm">Agent</h2>
        </div>
        <AgentChat />
      </div>
    </div>
  );
}
