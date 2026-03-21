"use client";

import { useState, useEffect } from "react";

interface Instrument {
  id: string;
  type: string;
  name: string;
  connected: boolean;
  port?: string;
  details: Record<string, unknown>;
}

const MOCK_INSTRUMENTS: Instrument[] = [
  {
    id: "ad2",
    type: "scope",
    name: "Digilent Analog Discovery",
    connected: true,
    port: "/dev/ttyUSB0",
    details: {
      channels: 2,
      max_sample_rate: "100 MSa/s",
      bandwidth: "5 MHz",
      features: ["Scope", "Waveform Gen", "Logic Analyzer", "Protocol Decoder"],
    },
  },
  {
    id: "dps150",
    type: "psu",
    name: "FNIRSI DPS-150",
    connected: true,
    port: "/dev/ttyACM0",
    details: {
      max_voltage: "30V",
      max_current: "5.5A",
      features: ["Voltage Sweep", "Current Limit", "OVP/OCP", "Telemetry"],
    },
  },
  {
    id: "dut",
    type: "dut",
    name: "ESP32-S3 DevKitC-1 (DUT)",
    connected: true,
    port: "/dev/ttyACM1",
    details: {
      chip: "ESP32-S3",
      firmware: "benchy-dut v1.0.0",
      peripherals: ["PWM", "I2C", "UART", "CAN/TWAI", "GPIO", "ADC", "WiFi"],
    },
  },
  {
    id: "fixture",
    type: "fixture",
    name: "ESP32-S3 DevKitC-1 (Fixture)",
    connected: false,
    port: undefined,
    details: {
      chip: "ESP32-S3",
      firmware: "benchy-fixture v1.0.0",
      peripherals: [
        "I2C Slave",
        "CAN Partner",
        "DUT Reset",
        "Load Injection",
        "UART Relay",
      ],
    },
  },
];

const TYPE_LABELS: Record<string, string> = {
  scope: "SCOPE",
  psu: "PSU",
  dut: "DUT",
  fixture: "FIXTURE",
};

export default function InstrumentsPage() {
  const [instruments, setInstruments] = useState<Instrument[]>(MOCK_INSTRUMENTS);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = async () => {
    setRefreshing(true);
    try {
      const res = await fetch("/api/runs?action=instruments");
      if (res.ok) {
        const data = await res.json();
        if (data.instruments?.length) setInstruments(data.instruments);
      }
    } catch {
      // Keep mock data on failure
    }
    setRefreshing(false);
  };

  useEffect(() => {
    refresh();
  }, []);

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-lg font-semibold">Instruments</h1>
          <p className="text-sm text-muted-foreground">
            Connected hardware on the test bench
          </p>
        </div>
        <button
          onClick={refresh}
          disabled={refreshing}
          className="text-xs border border-border px-3 py-1.5 rounded-md hover:bg-surface-2 transition-colors disabled:opacity-50"
        >
          {refreshing ? "Scanning..." : "Refresh"}
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {instruments.map((inst) => (
          <div
            key={inst.id}
            className="bg-card border border-border rounded-md p-6"
          >
            <div className="flex items-center gap-3 mb-4">
              <div className="px-2 py-1 rounded-sm bg-secondary text-secondary-foreground font-mono text-[10px] uppercase tracking-wide">
                {TYPE_LABELS[inst.type] || inst.type}
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{inst.name}</span>
                  <div
                    className={`w-2 h-2 rounded-full ${inst.connected ? "bg-success" : "bg-destructive"}`}
                  />
                </div>
                <span className="text-xs text-muted-foreground font-mono">
                  {inst.port || "not connected"}
                </span>
              </div>
            </div>

            <div className="space-y-1.5">
              {Object.entries(inst.details).map(([key, value]) => (
                <div
                  key={key}
                  className="flex items-start justify-between text-xs"
                >
                  <span className="text-muted-foreground">{key}</span>
                  <span className="text-right max-w-[60%]">
                    {Array.isArray(value) ? value.join(", ") : String(value)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
