"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";

interface WaveformChartProps {
  time: number[];
  ch1: number[];
  ch2?: number[];
  title?: string;
  brownoutThreshold?: number;
}

export function WaveformChart({
  time,
  ch1,
  ch2,
  title,
  brownoutThreshold,
}: WaveformChartProps) {
  const data = time.map((t, i) => ({
    time: Math.round(t * 1000) / 1000,
    ch1: ch1[i],
    ...(ch2 ? { ch2: ch2[i] } : {}),
  }));

  return (
    <div className="bg-card rounded-md border border-border p-6">
      {title && (
        <h3 className="text-sm font-medium mb-4 text-muted-foreground">
          {title}
        </h3>
      )}
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.88 0.008 75)" />
          <XAxis
            dataKey="time"
            stroke="oklch(0.46 0.01 60)"
            fontSize={10}
            fontFamily="var(--font-plex-mono)"
            tickFormatter={(v) => `${v}ms`}
          />
          <YAxis
            stroke="oklch(0.46 0.01 60)"
            fontSize={10}
            fontFamily="var(--font-plex-mono)"
            domain={["auto", "auto"]}
            tickFormatter={(v) => `${v}V`}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "oklch(0.99 0.004 85)",
              border: "1px solid oklch(0.88 0.008 75)",
              borderRadius: "2px",
              fontSize: 12,
              fontFamily: "var(--font-plex-mono)",
            }}
            labelFormatter={(v) => `${v} ms`}
            formatter={(value) => [`${Number(value).toFixed(3)} V`]}
          />
          <Line
            type="monotone"
            dataKey="ch1"
            stroke="oklch(0.32 0.08 250)"
            dot={false}
            strokeWidth={1.5}
            name="CH1"
          />
          {ch2 && (
            <Line
              type="monotone"
              dataKey="ch2"
              stroke="oklch(0.50 0.12 165)"
              dot={false}
              strokeWidth={1.5}
              name="CH2"
            />
          )}
          {brownoutThreshold && (
            <ReferenceLine
              y={brownoutThreshold}
              stroke="oklch(0.577 0.245 27.325)"
              strokeDasharray="5 5"
              label={{
                value: `Brownout ${brownoutThreshold}V`,
                fill: "oklch(0.577 0.245 27.325)",
                fontSize: 10,
                position: "right",
              }}
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
