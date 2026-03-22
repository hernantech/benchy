"use client";

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Cell,
} from "recharts";

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
// ResultChart — auto-detect and render charts from tool results
// ---------------------------------------------------------------------------

const CHART_COLORS = {
  primary: "oklch(0.50 0.12 165)",   // accent/teal
  secondary: "oklch(0.65 0.15 250)", // blue
  warn: "oklch(0.75 0.15 75)",       // yellow
  grid: "oklch(0.30 0.02 250)",      // subtle grid
  text: "oklch(0.65 0.02 250)",      // axis text
};

/** Generate simulated PWM square wave data points */
function generatePWMWaveform(freq: number, dutyPct: number, cycles: number = 4): { t: number; v: number }[] {
  const period = 1 / freq;
  const highTime = period * (dutyPct / 100);
  const pointsPerCycle = 100;
  const points: { t: number; v: number }[] = [];

  for (let c = 0; c < cycles; c++) {
    const offset = c * period;
    // Rising edge
    points.push({ t: (offset) * 1000, v: 0 });
    points.push({ t: (offset) * 1000, v: 3.3 });
    // High duration
    points.push({ t: (offset + highTime) * 1000, v: 3.3 });
    // Falling edge
    points.push({ t: (offset + highTime) * 1000, v: 0 });
    // Low duration
    points.push({ t: (offset + period) * 1000, v: 0 });
  }
  return points;
}

/** Extract nested response object from tool result */
function getResponseObj(result: unknown): Record<string, unknown> | null {
  if (!result || typeof result !== "object") return null;
  const r = result as Record<string, unknown>;
  // Some results nest under "response"
  if (r.response && typeof r.response === "object") {
    return r.response as Record<string, unknown>;
  }
  return r;
}

function ResultChart({ toolName, result }: { toolName: string; result: unknown }) {
  const chart = useMemo(() => {
    const resp = getResponseObj(result);
    if (!resp) return null;

    const cmd = resp.cmd as string | undefined;

    // --- PWM: simulated waveform ---
    if (cmd === "pwm" || toolName === "dut_command" && resp.duty_pct !== undefined) {
      const freq = (resp.freq as number) || 1000;
      const duty = (resp.duty_pct as number) || 50;
      const pin = resp.pin as number;
      const waveform = generatePWMWaveform(freq, duty);

      return {
        type: "pwm" as const,
        title: `PWM — GPIO${pin} @ ${freq >= 1000 ? `${freq / 1000}kHz` : `${freq}Hz`}, ${duty}% duty`,
        data: waveform,
        freq,
        duty,
      };
    }

    // --- Scope capture: metrics bar chart ---
    if (resp.stats && typeof resp.stats === "object") {
      const stats = resp.stats as Record<string, number>;
      const data = Object.entries(stats)
        .filter(([, v]) => typeof v === "number")
        .map(([k, v]) => ({
          name: k.replace("v_", "V_").replace("_", " "),
          value: Number(v.toFixed(4)),
        }));
      if (data.length > 0) {
        return { type: "bar" as const, title: "Scope Capture Stats", data };
      }
    }

    // --- Signal integrity: metrics bar ---
    if (resp.rise_time_ns !== undefined || resp.overshoot_pct !== undefined) {
      const data: { name: string; value: number; unit: string }[] = [];
      if (resp.rise_time_ns !== undefined) data.push({ name: "Rise", value: resp.rise_time_ns as number, unit: "ns" });
      if (resp.fall_time_ns !== undefined) data.push({ name: "Fall", value: resp.fall_time_ns as number, unit: "ns" });
      if (resp.overshoot_pct !== undefined) data.push({ name: "Overshoot", value: resp.overshoot_pct as number, unit: "%" });
      if (resp.undershoot_pct !== undefined) data.push({ name: "Undershoot", value: resp.undershoot_pct as number, unit: "%" });
      if (data.length > 0) {
        return { type: "bar" as const, title: "Signal Integrity", data };
      }
    }

    // --- ADC read: bar chart of value ---
    if (cmd === "adc_read" && resp.voltage !== undefined) {
      const data = [
        { name: "Voltage", value: resp.voltage as number },
        ...(resp.raw !== undefined ? [{ name: "Raw", value: resp.raw as number }] : []),
      ];
      return { type: "bar" as const, title: `ADC Pin ${resp.pin}`, data };
    }

    // --- PSU state: voltage + current ---
    if (resp.voltage !== undefined && resp.current !== undefined && (resp.power !== undefined || resp.temperature !== undefined)) {
      const data: { name: string; value: number }[] = [
        { name: "Voltage (V)", value: resp.voltage as number },
        { name: "Current (A)", value: resp.current as number },
      ];
      if (resp.power !== undefined) data.push({ name: "Power (W)", value: resp.power as number });
      return { type: "bar" as const, title: "PSU State", data };
    }

    // --- Sweep voltage: line chart ---
    if (Array.isArray(resp.points) || Array.isArray(resp.data)) {
      const points = (resp.points || resp.data) as Record<string, unknown>[];
      if (points.length > 2 && points[0] && typeof points[0].voltage === "number") {
        const data = points.map((p) => ({
          voltage: (p.voltage as number).toFixed(2),
          current: p.current as number,
        }));
        return { type: "line" as const, title: "Voltage Sweep", data, xKey: "voltage", yKey: "current" };
      }
    }

    return null;
  }, [toolName, result]);

  if (!chart) return null;

  return (
    <div className="border-t border-border p-2">
      <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1 px-1">
        {chart.title}
      </div>
      <div className="h-32 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {chart.type === "pwm" ? (
            <LineChart data={chart.data} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
              <XAxis
                dataKey="t"
                tick={{ fontSize: 9, fill: CHART_COLORS.text }}
                tickFormatter={(v) => `${Number(v).toFixed(1)}`}
                label={{ value: "ms", position: "insideBottomRight", offset: -2, fontSize: 9, fill: CHART_COLORS.text }}
              />
              <YAxis
                domain={[-0.3, 3.6]}
                ticks={[0, 3.3]}
                tick={{ fontSize: 9, fill: CHART_COLORS.text }}
                tickFormatter={(v) => `${v}V`}
                width={32}
              />
              <ReferenceLine y={3.3} stroke={CHART_COLORS.warn} strokeDasharray="3 3" strokeWidth={0.5} />
              <Tooltip
                contentStyle={{ fontSize: 10, background: "oklch(0.18 0.02 250)", border: "1px solid oklch(0.30 0.02 250)", borderRadius: 4 }}
                labelFormatter={(v) => `${Number(v).toFixed(2)} ms`}
                formatter={(v) => [`${Number(v).toFixed(1)} V`, "Voltage"]}
              />
              <Line type="stepAfter" dataKey="v" stroke={CHART_COLORS.primary} strokeWidth={1.5} dot={false} isAnimationActive={false} />
            </LineChart>
          ) : chart.type === "line" ? (
            <LineChart data={chart.data} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
              <XAxis dataKey={chart.xKey} tick={{ fontSize: 9, fill: CHART_COLORS.text }} />
              <YAxis tick={{ fontSize: 9, fill: CHART_COLORS.text }} width={40} />
              <Tooltip contentStyle={{ fontSize: 10, background: "oklch(0.18 0.02 250)", border: "1px solid oklch(0.30 0.02 250)", borderRadius: 4 }} />
              <Line type="monotone" dataKey={chart.yKey} stroke={CHART_COLORS.primary} strokeWidth={1.5} dot={{ r: 2 }} />
            </LineChart>
          ) : (
            <BarChart data={chart.data} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
              <XAxis dataKey="name" tick={{ fontSize: 9, fill: CHART_COLORS.text }} />
              <YAxis tick={{ fontSize: 9, fill: CHART_COLORS.text }} width={40} />
              <Tooltip contentStyle={{ fontSize: 10, background: "oklch(0.18 0.02 250)", border: "1px solid oklch(0.30 0.02 250)", borderRadius: 4 }} />
              <Bar dataKey="value" radius={[2, 2, 0, 0]}>
                {chart.data.map((_: unknown, i: number) => (
                  <Cell key={i} fill={i % 2 === 0 ? CHART_COLORS.primary : CHART_COLORS.secondary} />
                ))}
              </Bar>
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
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

      {/* Auto-generated chart from result data */}
      {hasResult && <ResultChart toolName={tc.name} result={tc.result} />}

      {/* Chart image from server (scope captures) */}
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

      // Handle both SSE (text/event-stream) and plain JSON responses
      const contentType = res.headers.get("Content-Type") || "";
      if (!contentType.includes("text/event-stream")) {
        // Plain JSON fallback — backend doesn't have SSE yet
        stopTimer();
        const data = await res.json();
        const toolCalls = (data.toolCalls || []).map((tc: Record<string, unknown>) => ({
          ...tc,
          status: "done" as const,
        }));
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: data.text || "", toolCalls },
        ]);
        setStatus({ phase: "done", message: "Done", elapsed_s: Math.round((Date.now() - startTimeRef.current) / 1000), stepCount: toolCalls.length });
        setIsLoading(false);
        setTimeout(() => setStatus({ phase: "idle", message: "", elapsed_s: 0, stepCount: 0 }), 2000);
        return;
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
