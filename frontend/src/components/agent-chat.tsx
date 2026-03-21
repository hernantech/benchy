"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  result?: unknown;
  status: "running" | "done" | "error";
  duration_ms?: number;
  error?: string;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  toolCalls?: ToolCall[];
}

interface AgentStatus {
  phase: "idle" | "thinking" | "tool" | "done" | "error";
  message: string;
  elapsed_s: number;
  currentTool?: string;
  stepCount: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SUGGESTED_PROMPTS = [
  "Run a boot stress test — sweep voltage from 3.6V to 2.5V and find the brownout threshold",
  "Generate a 1kHz PWM on GPIO4 and verify the frequency and duty cycle",
  "Check I2C signal integrity between DUT and fixture at 400kHz",
  "Characterize the 3V3 rail ripple under WiFi load",
];

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function formatArgs(args: Record<string, unknown>): string {
  return Object.entries(args)
    .filter(([, v]) => v !== undefined)
    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`)
    .join("\n");
}

function formatResult(result: unknown): {
  summary: string;
  chartUrl?: string;
  detail?: string;
} {
  if (result === undefined || result === null) return { summary: "no result" };
  if (typeof result === "string") return { summary: result };
  if (typeof result !== "object") return { summary: String(result) };

  const r = result as Record<string, unknown>;
  const lines: string[] = [];
  let chartUrl: string | undefined;

  if (typeof r.chart_full_url === "string") chartUrl = r.chart_full_url;
  else if (typeof r.chart_url === "string") chartUrl = r.chart_url as string;

  for (const nested of ["scope", "execution"] as const) {
    const sub = r[nested] as Record<string, unknown> | undefined;
    if (sub?.chart_full_url && typeof sub.chart_full_url === "string") {
      chartUrl = sub.chart_full_url;
    }
  }

  for (const [k, v] of Object.entries(r)) {
    if (k === "chart_url" || k === "chart_full_url" || k === "ok") continue;
    if (v === undefined || v === null) continue;
    if (typeof v === "object" && !Array.isArray(v)) {
      const sub = v as Record<string, unknown>;
      const subLines = Object.entries(sub)
        .filter(([sk]) => sk !== "chart_url" && sk !== "chart_full_url")
        .map(
          ([sk, sv]) =>
            `  ${sk}: ${typeof sv === "object" ? JSON.stringify(sv) : sv}`
        );
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

// ---------------------------------------------------------------------------
// ToolCallBlock — individual tool step rendering
// ---------------------------------------------------------------------------

function ToolCallBlock({ tc }: { tc: ToolCall }) {
  const [expanded, setExpanded] = useState(false);
  const { summary, chartUrl, detail } = formatResult(tc.result);
  const hasResult = tc.status !== "running";

  return (
    <div className="border border-border rounded-md overflow-hidden text-xs font-mono">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 bg-muted hover:bg-surface-2 transition-colors text-left"
      >
        <span
          className={`w-1.5 h-1.5 rounded-full shrink-0 ${
            tc.status === "running"
              ? "bg-accent animate-pulse"
              : tc.status === "error"
                ? "bg-destructive"
                : "bg-success"
          }`}
        />
        <span className="text-accent font-medium">{tc.name}</span>
        {tc.status === "running" && (
          <span className="text-muted-foreground text-[10px]">running</span>
        )}
        {tc.duration_ms !== undefined && (
          <span className="text-muted-foreground text-[10px]">
            {(tc.duration_ms / 1000).toFixed(1)}s
          </span>
        )}
        <span className="text-muted-foreground ml-auto">
          {expanded ? "▾" : "▸"}
        </span>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="border-t border-border">
          <div className="px-2.5 py-1.5 border-b border-border">
            <div className="text-muted-foreground text-[10px] uppercase tracking-wide mb-0.5">
              input
            </div>
            <pre className="text-foreground whitespace-pre-wrap">
              {formatArgs(tc.args)}
            </pre>
          </div>
          {hasResult && (
            <div className="px-2.5 py-1.5">
              <div className="text-muted-foreground text-[10px] uppercase tracking-wide mb-0.5">
                {tc.status === "error" ? "error" : "output"}
              </div>
              <pre
                className={`whitespace-pre-wrap ${tc.status === "error" ? "text-destructive" : "text-foreground"}`}
              >
                {tc.error || detail || summary}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Collapsed: compact summary */}
      {!expanded && hasResult && (
        <div className="px-2.5 py-1 border-t border-border text-muted-foreground truncate">
          {tc.error || summary.split("\n")[0]}
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
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = "none";
            }}
          />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// StatusBar — shows what the agent is doing right now
// ---------------------------------------------------------------------------

function StatusBar({ status }: { status: AgentStatus }) {
  if (status.phase === "idle") return null;

  return (
    <div className="border border-border rounded-md overflow-hidden text-xs font-mono bg-muted">
      <div className="flex items-center gap-2 px-3 py-2">
        {/* Animated indicator */}
        <div className="relative flex items-center justify-center w-4 h-4 shrink-0">
          {status.phase !== "done" && status.phase !== "error" ? (
            <>
              <span className="absolute w-3 h-3 rounded-full bg-accent/30 animate-ping" />
              <span className="relative w-2 h-2 rounded-full bg-accent" />
            </>
          ) : status.phase === "error" ? (
            <span className="w-2 h-2 rounded-full bg-destructive" />
          ) : (
            <span className="w-2 h-2 rounded-full bg-success" />
          )}
        </div>

        {/* Status message */}
        <span className="text-foreground font-medium">{status.message}</span>

        {/* Step counter */}
        {status.stepCount > 0 && (
          <span className="text-muted-foreground">
            step {status.stepCount}
          </span>
        )}

        {/* Timer */}
        <span className="text-muted-foreground ml-auto tabular-nums">
          {status.elapsed_s}s
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SSE parser — reads the event stream from the API
// ---------------------------------------------------------------------------

async function readSSEStream(
  response: Response,
  callbacks: {
    onStatus: (phase: string, message: string) => void;
    onToolStart: (name: string, args: Record<string, unknown>, step: number) => void;
    onToolEnd: (name: string, result: unknown, step: number, duration_ms: number) => void;
    onToolError: (name: string, error: string, step: number, duration_ms: number) => void;
    onDone: (text: string, toolCalls: ToolCall[]) => void;
    onError: (message: string) => void;
  }
) {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // Parse SSE events from buffer
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || ""; // keep incomplete last part

    for (const part of parts) {
      if (!part.trim()) continue;

      let eventType = "message";
      let data = "";

      for (const line of part.split("\n")) {
        if (line.startsWith("event: ")) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith("data: ")) {
          data = line.slice(6);
        }
      }

      if (!data) continue;

      try {
        const parsed = JSON.parse(data);

        switch (eventType) {
          case "status":
            callbacks.onStatus(parsed.phase, parsed.message);
            break;
          case "tool_start":
            callbacks.onToolStart(parsed.name, parsed.args, parsed.step);
            break;
          case "tool_end":
            callbacks.onToolEnd(parsed.name, parsed.result, parsed.step, parsed.duration_ms);
            break;
          case "tool_error":
            callbacks.onToolError(parsed.name, parsed.error, parsed.step, parsed.duration_ms);
            break;
          case "done":
            callbacks.onDone(parsed.text, parsed.toolCalls);
            break;
          case "error":
            callbacks.onError(parsed.message);
            break;
        }
      } catch {
        // skip malformed events
      }
    }
  }
}

// ---------------------------------------------------------------------------
// AgentChat — main component
// ---------------------------------------------------------------------------

export function AgentChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [liveTools, setLiveTools] = useState<ToolCall[]>([]);
  const [status, setStatus] = useState<AgentStatus>({
    phase: "idle",
    message: "",
    elapsed_s: 0,
    stepCount: 0,
  });
  const scrollRef = useRef<HTMLDivElement>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number>(0);

  // Auto-scroll on any state change
  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
  }, [messages, liveTools, status]);

  // Elapsed timer
  const startTimer = useCallback(() => {
    startTimeRef.current = Date.now();
    timerRef.current = setInterval(() => {
      setStatus((prev) => ({
        ...prev,
        elapsed_s: Math.round((Date.now() - startTimeRef.current) / 1000),
      }));
    }, 1000);
  }, []);

  const stopTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => stopTimer();
  }, [stopTimer]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMessage }]);
    setIsLoading(true);
    setLiveTools([]);
    setStatus({
      phase: "thinking",
      message: "Agent is planning...",
      elapsed_s: 0,
      stepCount: 0,
    });
    startTimer();

    try {
      const res = await fetch("/api/agent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: [...messages, { role: "user", content: userMessage }],
        }),
      });

      if (!res.ok) {
        const text = await res.text();
        let errMsg = `Agent request failed (${res.status})`;
        try {
          errMsg = JSON.parse(text).error || errMsg;
        } catch { /* use default */ }
        throw new Error(errMsg);
      }

      await readSSEStream(res, {
        onStatus: (phase, message) => {
          setStatus((prev) => ({ ...prev, phase: phase as AgentStatus["phase"], message }));
        },

        onToolStart: (name, args, step) => {
          setStatus((prev) => ({
            ...prev,
            phase: "tool",
            message: `Running ${name}...`,
            currentTool: name,
            stepCount: step,
          }));
          setLiveTools((prev) => [
            ...prev,
            { name, args, status: "running" },
          ]);
        },

        onToolEnd: (name, result, _step, duration_ms) => {
          setLiveTools((prev) =>
            prev.map((tc) =>
              tc.name === name && tc.status === "running"
                ? { ...tc, result, status: "done", duration_ms }
                : tc
            )
          );
          setStatus((prev) => ({
            ...prev,
            phase: "thinking",
            message: "Agent is reasoning...",
            currentTool: undefined,
          }));
        },

        onToolError: (name, error, _step, duration_ms) => {
          setLiveTools((prev) =>
            prev.map((tc) =>
              tc.name === name && tc.status === "running"
                ? { ...tc, status: "error", error, duration_ms }
                : tc
            )
          );
          setStatus((prev) => ({
            ...prev,
            phase: "thinking",
            message: "Agent is reasoning...",
            currentTool: undefined,
          }));
        },

        onDone: (text, _toolCalls) => {
          stopTimer();
          // Merge live tools into the final message
          setMessages((prev) => [
            ...prev,
            {
              role: "assistant",
              content: text || "",
              toolCalls: undefined, // tools are already shown live
            },
          ]);
          setStatus((prev) => ({
            ...prev,
            phase: "done",
            message: "Done",
          }));
          // Move live tools into the last assistant message
          setLiveTools((prev) => {
            if (prev.length > 0) {
              setMessages((msgs) => {
                const last = msgs[msgs.length - 1];
                if (last?.role === "assistant") {
                  return [
                    ...msgs.slice(0, -1),
                    { ...last, toolCalls: prev },
                  ];
                }
                return msgs;
              });
            }
            return [];
          });
        },

        onError: (message) => {
          stopTimer();
          setStatus((prev) => ({
            ...prev,
            phase: "error",
            message: `Error: ${message}`,
          }));
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: `Error: ${message}` },
          ]);
          setLiveTools([]);
        },
      });
    } catch (err) {
      stopTimer();
      setStatus({
        phase: "error",
        message: "Connection failed",
        elapsed_s: Math.round((Date.now() - startTimeRef.current) / 1000),
        stepCount: 0,
      });
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `Error: ${err instanceof Error ? err.message : "Failed to reach agent."}`,
        },
      ]);
      setLiveTools([]);
    } finally {
      setIsLoading(false);
      // Reset status after a brief delay so user sees "Done"
      setTimeout(() => {
        setStatus({
          phase: "idle",
          message: "",
          elapsed_s: 0,
          stepCount: 0,
        });
      }, 2000);
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Messages area */}
      <div ref={scrollRef} className="flex-1 overflow-auto p-4 space-y-3">
        {messages.length === 0 && !isLoading && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center max-w-sm">
              <div className="text-3xl mb-2 font-mono">&gt;_</div>
              <h2 className="text-sm font-semibold mb-1">Benchy Agent</h2>
              <p className="text-muted-foreground text-xs mb-4">
                Describe what to test. The agent controls real instruments and
                reports measurements.
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
                {msg.toolCalls && msg.toolCalls.length > 0 && (
                  <div className="space-y-1.5">
                    {msg.toolCalls.map((tc, j) => (
                      <ToolCallBlock key={j} tc={tc} />
                    ))}
                  </div>
                )}
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

        {/* Live tool calls (streaming in) */}
        {liveTools.length > 0 && (
          <div className="space-y-1.5">
            {liveTools.map((tc, j) => (
              <ToolCallBlock key={j} tc={tc} />
            ))}
          </div>
        )}

        {/* Status bar (shows during loading) */}
        {isLoading && <StatusBar status={status} />}
      </div>

      {/* Input bar */}
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
