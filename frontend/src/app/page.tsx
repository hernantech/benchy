"use client";

import { useState } from "react";
import { RunList } from "@/components/run-list";
import { RunDetail } from "@/components/run-detail";
import type { Run } from "@/lib/types";

export default function HomePage() {
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);

  return (
    <div className="flex h-[calc(100vh-56px)]">
      {/* Left sidebar — run list */}
      <div className="w-80 border-r border-border flex flex-col bg-card">
        <div className="p-4 border-b border-border flex items-center justify-between">
          <h2 className="font-semibold text-sm">Test Runs</h2>
          <a
            href="/agent"
            className="bg-primary text-primary-foreground text-xs font-medium px-3 py-1.5 rounded-md hover:bg-primary/90 transition-colors"
          >
            New Run
          </a>
        </div>
        <RunList selectedId={selectedRun?.id} onSelect={setSelectedRun} />
      </div>

      {/* Main area — run detail or empty state */}
      <div className="flex-1 overflow-auto">
        {selectedRun ? (
          <RunDetail run={selectedRun} />
        ) : (
          <div className="flex items-center justify-center h-full text-muted-foreground">
            <div className="text-center">
              <div className="text-4xl mb-3 font-mono">&gt;_</div>
              <p className="text-sm">Select a run or start a new one</p>
              <a
                href="/agent"
                className="inline-block mt-4 bg-primary text-primary-foreground text-sm font-medium px-4 py-2 rounded-md hover:bg-primary/90 transition-colors"
              >
                Start Agent Run
              </a>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
