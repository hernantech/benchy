"use client";

import { useState, useRef, useEffect } from "react";

interface Message {
  role: "user" | "assistant";
  content: string;
  toolCalls?: { name: string; args: Record<string, unknown>; result?: string }[];
}

const SUGGESTED_PROMPTS = [
  "Run a boot stress test — sweep voltage from 3.6V to 2.5V and find the brownout threshold",
  "Generate a 1kHz PWM on GPIO4 and verify the frequency and duty cycle",
  "Check I2C signal integrity between DUT and fixture at 400kHz",
  "Characterize the 3V3 rail ripple under WiFi load",
];

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

      if (!res.ok) throw new Error("Agent request failed");

      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.text || "No response",
          toolCalls: data.toolCalls,
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Error: Failed to reach agent." },
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
                Tell the agent what to test. It will control the power supply,
                oscilloscope, and ESP32 boards to run experiments.
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
          <div
            key={i}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[85%] rounded-md px-3 py-2 ${
                msg.role === "user"
                  ? "bg-primary text-primary-foreground"
                  : "bg-card border border-border"
              }`}
            >
              <p className="text-sm whitespace-pre-wrap">{msg.content}</p>

              {msg.toolCalls && msg.toolCalls.length > 0 && (
                <div className="mt-2 space-y-1.5">
                  {msg.toolCalls.map((tc, j) => (
                    <div
                      key={j}
                      className="bg-muted rounded-sm p-2 text-xs font-mono"
                    >
                      <div className="text-accent">{tc.name}</div>
                      <div className="text-muted-foreground">
                        {JSON.stringify(tc.args)}
                      </div>
                      {tc.result && (
                        <div className="mt-1 text-foreground">{tc.result}</div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-card border border-border rounded-md px-3 py-2">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <div className="w-2 h-2 bg-primary rounded-full animate-pulse" />
                Running experiment...
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
