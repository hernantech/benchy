"use client";

import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";

interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  result?: unknown;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  toolCalls?: ToolCall[];
}

const SUGGESTED_PROMPTS = [
  "Run a boot stress test — sweep voltage from 3.6V to 2.5V and find the brownout threshold",
  "Generate a 1kHz PWM on GPIO4 and verify the frequency and duty cycle",
  "Check I2C signal integrity between DUT and fixture at 400kHz",
  "Characterize the 3V3 rail ripple under WiFi load",
];

// Format tool args as key=value pairs, one per line
function formatArgs(args: Record<string, unknown>): string {
  return Object.entries(args)
    .filter(([, v]) => v !== undefined)
    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`)
    .join("\n");
}

// Extract key fields from a tool result for compact display
function formatResult(result: unknown): { summary: string; chartUrl?: string; detail?: string } {
  if (result === undefined || result === null) return { summary: "no result" };
  if (typeof result === "string") return { summary: result };
  if (typeof result !== "object") return { summary: String(result) };

  const r = result as Record<string, unknown>;
  const lines: string[] = [];
  let chartUrl: string | undefined;

  // Pull out chart URLs
  if (typeof r.chart_full_url === "string") chartUrl = r.chart_full_url;
  else if (typeof r.chart_url === "string") chartUrl = r.chart_url as string;

  // Check nested scope/execution objects for charts too
  for (const nested of ["scope", "execution"] as const) {
    const sub = r[nested] as Record<string, unknown> | undefined;
    if (sub?.chart_full_url && typeof sub.chart_full_url === "string") {
      chartUrl = sub.chart_full_url;
    }
  }

  // Build summary from interesting fields
  for (const [k, v] of Object.entries(r)) {
    if (k === "chart_url" || k === "chart_full_url" || k === "ok") continue;
    if (v === undefined || v === null) continue;
    if (typeof v === "object" && !Array.isArray(v)) {
      // Nested object — show one level
      const sub = v as Record<string, unknown>;
      const subLines = Object.entries(sub)
        .filter(([sk]) => sk !== "chart_url" && sk !== "chart_full_url")
        .map(([sk, sv]) => `  ${sk}: ${typeof sv === "object" ? JSON.stringify(sv) : sv}`);
      if (subLines.length > 0) {
        lines.push(`${k}:`);
        lines.push(...subLines);
      }
    } else {
      lines.push(`${k}: ${Array.isArray(v) ? JSON.stringify(v) : v}`);
    }
  }

  const summary = lines.slice(0, 8).join("\n");
  const detail = lines.length > 8 ? lines.join("\n") : undefined;

  return { summary, chartUrl, detail };
}

function ToolCallBlock({ tc }: { tc: ToolCall }) {
  const [expanded, setExpanded] = useState(false);
  const { summary, chartUrl, detail } = formatResult(tc.result);
  const hasResult = tc.result !== undefined;
  const ok = typeof tc.result === "object" && tc.result !== null && (tc.result as Record<string, unknown>).ok === true;
  const failed = typeof tc.result === "object" && tc.result !== null && (tc.result as Record<string, unknown>).ok === false;

  return (
    <div className="border border-border rounded-md overflow-hidden text-xs font-mono">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 bg-muted hover:bg-surface-2 transition-colors text-left"
      >
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
          !hasResult ? "bg-warning animate-pulse" : ok ? "bg-success" : failed ? "bg-destructive" : "bg-muted-foreground"
        }`} />
        <span className="text-accent font-medium">{tc.name}</span>
        <span className="text-muted-foreground ml-auto">{expanded ? "▾" : "▸"}</span>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="border-t border-border">
          {/* Args */}
          <div className="px-2.5 py-1.5 border-b border-border">
            <div className="text-muted-foreground text-[10px] uppercase tracking-wide mb-0.5">input</div>
            <pre className="text-foreground whitespace-pre-wrap">{formatArgs(tc.args)}</pre>
          </div>

          {/* Result */}
          {hasResult && (
            <div className="px-2.5 py-1.5">
              <div className="text-muted-foreground text-[10px] uppercase tracking-wide mb-0.5">output</div>
              <pre className="text-foreground whitespace-pre-wrap">{detail || summary}</pre>
            </div>
          )}
        </div>
      )}

      {/* Collapsed: show compact summary */}
      {!expanded && hasResult && (
        <div className="px-2.5 py-1 border-t border-border text-muted-foreground truncate">
          {summary.split("\n")[0]}
        </div>
      )}

      {/* Chart image */}
      {chartUrl && (
        <div className="border-t border-border p-2">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={chartUrl}
            alt={`${tc.name} waveform`}
            className="w-full rounded-sm"
            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
          />
        </div>
      )}
    </div>
  );
}

export function AgentChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
  }, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMessage }]);
    setIsLoading(true);

    try {
      const res = await fetch("/api/agent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: [...messages, { role: "user", content: userMessage }],
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => null);
        throw new Error(errData?.error || `Agent request failed (${res.status})`);
      }

      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.text || "",
          toolCalls: data.toolCalls,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Error: ${err instanceof Error ? err.message : "Failed to reach agent."}` },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-auto p-4 space-y-3">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center max-w-sm">
              <div className="text-3xl mb-2 font-mono">&gt;_</div>
              <h2 className="text-sm font-semibold mb-1">Benchy Agent</h2>
              <p className="text-muted-foreground text-xs mb-4">
                Describe what to test. The agent controls real instruments
                and reports measurements.
              </p>
              <div className="grid grid-cols-1 gap-1.5 text-left">
                {SUGGESTED_PROMPTS.map((prompt) => (
                  <button
                    key={prompt}
                    onClick={() => setInput(prompt)}
                    className="text-xs text-left p-2.5 rounded-md border border-border hover:bg-surface-2 transition-colors text-muted-foreground hover:text-foreground"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i}>
            {msg.role === "user" ? (
              <div className="flex justify-end">
                <div className="max-w-[85%] rounded-md px-3 py-2 bg-primary text-primary-foreground">
                  <div className="text-sm prose prose-sm prose-neutral max-w-none [&_pre]:bg-muted [&_pre]:p-2 [&_pre]:rounded-sm [&_pre]:text-xs [&_pre]:font-mono [&_code]:text-xs [&_code]:font-mono [&_p]:my-1 [&_ul]:my-1 [&_ol]:my-1 [&_li]:my-0.5 [&_h1]:text-base [&_h2]:text-sm [&_h3]:text-sm [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-medium [&_table]:text-xs [&_th]:px-2 [&_th]:py-1 [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-border [&_td]:border [&_td]:border-border">
                    <ReactMarkdown>{msg.content}</ReactMarkdown>
                  </div>
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                {/* Tool calls — shown before text like Claude Code */}
                {msg.toolCalls && msg.toolCalls.length > 0 && (
                  <div className="space-y-1.5">
                    {msg.toolCalls.map((tc, j) => (
                      <ToolCallBlock key={j} tc={tc} />
                    ))}
                  </div>
                )}

                {/* Text response */}
                {msg.content && (
                  <div className="max-w-[85%] rounded-md px-3 py-2 bg-card border border-border">
                    <div className="text-sm prose prose-sm prose-neutral max-w-none [&_pre]:bg-muted [&_pre]:p-2 [&_pre]:rounded-sm [&_pre]:text-xs [&_pre]:font-mono [&_code]:text-xs [&_code]:font-mono [&_p]:my-1 [&_ul]:my-1 [&_ol]:my-1 [&_li]:my-0.5 [&_h1]:text-base [&_h2]:text-sm [&_h3]:text-sm [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-medium [&_table]:text-xs [&_th]:px-2 [&_th]:py-1 [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-border [&_td]:border [&_td]:border-border">
                    <ReactMarkdown>{msg.content}</ReactMarkdown>
                  </div>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}

        {isLoading && (
          <div className="space-y-1.5">
            <div className="border border-border rounded-md overflow-hidden text-xs font-mono">
              <div className="flex items-center gap-2 px-2.5 py-1.5 bg-muted">
                <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                <span className="text-muted-foreground">running...</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-border p-3 bg-card">
        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Describe what to test..."
            className="flex-1 bg-transparent border border-input rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-[3px] focus:ring-ring/50 transition placeholder:text-muted-foreground"
            disabled={isLoading}
          />
          <button
            type="submit"
            disabled={isLoading || !input.trim()}
            className="bg-primary text-primary-foreground font-medium px-4 py-2 rounded-md text-sm hover:bg-primary/90 transition-colors disabled:opacity-50"
          >
            Run
          </button>
        </form>
      </div>
    </div>
  );
}
