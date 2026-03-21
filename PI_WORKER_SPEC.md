# BenchAgent — Pi Worker Spec

## Overview

Python HTTP server on RPi 5 that controls lab instruments and ESP32 boards.
Vercel Next.js backend calls it over Tailscale. No auth (Tailscale ACLs are the boundary).

```
Vercel Next.js (Gemini agent tool calls)
        │
        │ HTTP over Tailscale
        ▼
RPi 5 (FastAPI, port 8420)
  ├── USB ── Digilent Analog Discovery (dwfpy)
  ├── USB ── DPS-150 PSU (dps150 library)
  ├── USB ── ESP32-A serial (DUT, /dev/ttyACM0)
  └── USB ── ESP32-B serial (fixture, /dev/ttyACM1)
```

## Stack

- **FastAPI** + uvicorn (async, simple, fast to build)
- **dwfpy** — Analog Discovery wrapper (existing code in daemon-clean)
- **dps150** — PSU library (existing code in ~/work/galois/dps150)
- **pyserial** — ESP32 serial communication
- **matplotlib** — render waveform arrays to PNG (headless, Agg backend)

## Networking

- RPi 5 joins Tailscale with a static hostname (e.g., `benchagent-pi`)
- Vercel backend calls `http://benchagent-pi:8420/...`
- Tailscale handles auth/encryption. No API keys, no TLS config.
- If Tailscale DNS is flaky at the venue, fall back to Tailscale IP directly.

## USB Device Mapping

Stable device paths via udev rules or serial number lookup:

| Device | Identifier | Mapping |
|---|---|---|
| Analog Discovery | dwfpy auto-discovery (serial number) | Opened by wrapper |
| DPS-150 | USB VID `0x2E3C` / PID `0x5740` | `dps150.discovery.find_dps150_port()` |
| ESP32-A (DUT) | Specific USB serial number | `/dev/ttyACM0` or by-id symlink |
| ESP32-B (fixture) | Specific USB serial number | `/dev/ttyACM1` or by-id symlink |

---

## API Endpoints

### Health

#### `GET /health`
Returns device connection status.

```json
{
  "status": "ok",
  "devices": {
    "ad2": {"connected": true, "serial": "SN:210321A..."},
    "psu": {"connected": true, "model": "DPS-150", "input_voltage": 19.8},
    "esp32_a": {"connected": true, "port": "/dev/ttyACM0"},
    "esp32_b": {"connected": true, "port": "/dev/ttyACM1"}
  }
}
```

---

### Power Supply (DPS-150)

#### `POST /psu/configure`
Set voltage, current limit, and optionally enable output.

```json
// Request
{"voltage": 3.3, "current_limit": 0.5, "output": true}

// Response
{"ok": true, "voltage_setpoint": 3.3, "current_limit": 0.5, "output_enabled": true}
```

#### `GET /psu/state`
Read live telemetry.

```json
{
  "output_voltage": 3.31,
  "output_current": 0.148,
  "output_power": 0.490,
  "mode": "CV",
  "temperature": 32.5,
  "protection_state": "",
  "output_enabled": true
}
```

#### `POST /psu/sweep`
Sweep voltage and return measurements at each step. Blocks until complete.

```json
// Request
{"start": 3.6, "stop": 2.5, "step": -0.1, "dwell": 0.5}

// Response
{
  "points": [
    {"voltage_set": 3.6, "voltage_meas": 3.59, "current": 0.142, "power": 0.510, "temp": 32.5},
    {"voltage_set": 3.5, "voltage_meas": 3.49, "current": 0.143, "power": 0.499, "temp": 32.6},
    ...
  ]
}
```

#### `POST /psu/off`
Disable output immediately (safety).

---

### Oscilloscope / Analog Discovery

#### `POST /scope/capture`
Single-shot acquisition. Returns raw data + rendered PNG.

```json
// Request
{
  "channel": 1,
  "v_range": 5.0,
  "samples": 8192,
  "sample_rate": 1000000,
  "trigger_level": 1.5,
  "trigger_channel": 1,
  "offset": 0.0
}

// Response
{
  "data": [0.012, 0.015, 0.014, ...],
  "sample_rate": 1000000,
  "sample_count": 8192,
  "stats": {
    "v_min": 0.012,
    "v_max": 3.31,
    "v_mean": 3.28,
    "v_pp": 3.298,
    "v_rms": 2.89
  },
  "chart_url": "/artifacts/scope_capture_1711036800.png"
}
```

Stats are computed server-side from the raw array (numpy). Chart is rendered
via matplotlib and saved to disk. `chart_url` is served as a static file.

#### `POST /scope/measure`
Quick DC/RMS/frequency measurement without full capture.

```json
// Request
{"channel": 1, "measurement": "dc"}

// Response
{"channel": 1, "measurement": "dc", "value": 3.312, "unit": "V"}
```

Supported measurements: `dc`, `peak_to_peak`, `rms`, `frequency`.

#### `POST /scope/pulse_width`
Capture a GPIO timing pulse. Configures trigger, captures, measures pulse width.
Used for Mode 2 (ISA optimization) execution time measurement.

```json
// Request
{
  "channel": 1,
  "trigger_level": 1.5,
  "trigger_edge": "rising",
  "timeout_ms": 5000
}

// Response
{
  "pulse_width_ms": 12.34,
  "pulse_width_us": 12340,
  "v_high": 3.29,
  "v_low": 0.02,
  "chart_url": "/artifacts/pulse_1711036801.png"
}
```

---

### Protocol Decoders (Analog Discovery)

#### `POST /uart/capture`
Capture UART data from a DIO pin for a duration.

```json
// Request
{
  "rx_pin": 0,
  "baud": 115200,
  "duration_ms": 3000
}

// Response
{
  "data": "rst:0x1 (POWERON),boot:0x13...\nBrownout detector was triggered\n",
  "bytes_received": 342
}
```

#### `POST /i2c/capture`
Capture I2C traffic between two ESP32s.

```json
// Request
{
  "sda_pin": 0,
  "scl_pin": 1,
  "duration_ms": 1000
}

// Response
{
  "transactions": [
    {"type": "write", "address": "0x48", "data": "0x00", "ack": true},
    {"type": "read", "address": "0x48", "data": "0x1A3F", "ack": true}
  ],
  "bus_errors": 0
}
```

#### `POST /scope/signal_integrity`
Capture analog waveform of a protocol bus and measure signal quality.

```json
// Request
{"channel": 1, "samples": 8192, "sample_rate": 10000000}

// Response
{
  "rise_time_ns": 1800,
  "fall_time_ns": 450,
  "overshoot_pct": 12.3,
  "undershoot_pct": 3.1,
  "chart_url": "/artifacts/si_1711036802.png"
}
```

---

### ESP32 Control

#### `POST /esp32/{board}/serial/send`
Send a command string to an ESP32 over serial. Returns the response.

```json
// Request (board = "a" or "b")
{"command": "{\"kernel\": \"baseline\", \"iterations\": 1000}", "timeout_ms": 5000}

// Response
{"response": "{\"time_us\": 12340, \"result\": 1.23456, \"iterations\": 1000}"}
```

#### `POST /esp32/{board}/serial/read`
Read buffered serial output (UART logs, boot messages).

```json
// Request
{"timeout_ms": 3000, "until": "\n"}

// Response
{"data": "ESP-ROM:esp32s3-20210327\nBuild:Mar 27 2021\n...", "bytes": 156}
```

#### `POST /esp32/{board}/reset`
Reset an ESP32 via Board B's GPIO → Board A's EN pin (or USB-serial DTR).

```json
// Response
{"ok": true, "method": "gpio_en_pin"}
```

#### `POST /esp32/{board}/flash`
Compile and flash firmware. Blocks until complete (long-running).

```json
// Request
{
  "project_path": "/home/pi/benchagent/firmware/harness",
  "target": "esp32s3",
  "port": "/dev/ttyACM0"
}

// Response
{
  "ok": true,
  "build_time_s": 18.4,
  "flash_time_s": 6.2,
  "size_bytes": 284672
}
```

---

### Artifacts

#### `GET /artifacts/{filename}`
Serve static files (PNG charts, CSV data). Matplotlib renders are saved here.

Directory: `/tmp/benchagent/artifacts/` (ephemeral, cleared on restart).

---

### Compound Operations (convenience for the agent)

#### `POST /run/debug`
Execute a full Mode 1 debug cycle. Sets PSU, captures scope + UART, returns everything.

```json
// Request
{
  "psu_voltage": 3.3,
  "psu_current_limit": 0.15,
  "scope_channel": 1,
  "scope_v_range": 5.0,
  "scope_samples": 8192,
  "scope_sample_rate": 1000000,
  "scope_trigger_level": 1.5,
  "uart_rx_pin": 0,
  "uart_baud": 115200,
  "capture_duration_ms": 3000,
  "reset_before": true
}

// Response
{
  "psu": { "voltage": 3.31, "current": 0.148, "mode": "CV" },
  "scope": {
    "stats": { "v_min": 2.41, "v_max": 3.31, "v_pp": 0.90 },
    "chart_url": "/artifacts/debug_scope_1711036803.png"
  },
  "uart": {
    "data": "...Brownout detector was triggered\n",
    "bytes": 342
  },
  "brownout_detected": true
}
```

#### `POST /run/benchmark`
Execute a full Mode 2 benchmark cycle. Selects kernel on ESP32, captures timing pulse.

```json
// Request
{
  "kernel": "baseline",
  "iterations": 1000,
  "scope_channel": 1,
  "scope_trigger_level": 1.5,
  "measure_power": true
}

// Response
{
  "kernel": "baseline",
  "iterations": 1000,
  "execution": {
    "total_ms": 12.34,
    "per_iteration_us": 12.34,
    "chart_url": "/artifacts/bench_pulse_1711036804.png"
  },
  "power": {
    "avg_current_ma": 145,
    "avg_power_mw": 478,
    "energy_per_iter_uj": 1.78
  },
  "esp32_report": {
    "time_us": 12340,
    "result": 1.23456,
    "ccount_cycles": 2960000
  }
}
```

---

## Chart Rendering

All scope captures are rendered to PNG via matplotlib (Agg backend, headless):

- Dark background (matches the UI)
- Grid lines, axis labels with units
- Annotations for key measurements (v_min, v_max, pulse width)
- Saved to `/tmp/benchagent/artifacts/`
- Filename includes timestamp for uniqueness
- Resolution: 800x400px (fast to render, good for Gemini vision)

For before/after comparisons, the Vercel frontend handles overlay rendering
using the raw `data` arrays from two captures.

---

## Error Handling

- All endpoints return `{"error": "message", "code": "DEVICE_DISCONNECTED"}` on failure
- PSU safety: if any endpoint fails mid-operation, PSU output is disabled as a `finally` block
- Serial timeouts: configurable per-request, default 5000ms
- Device reconnection: if AD2 or DPS-150 disconnects, next request attempts reconnect once

## Safety Clamps (hardcoded, not configurable)

```python
PSU_MAX_VOLTAGE = 5.5    # never exceed — ESP32 absolute max is 3.6V on 3V3, 5.5V on VIN
PSU_MAX_CURRENT = 1.0    # 1A is plenty for ESP32 dev boards
```

Any request exceeding these is rejected with 400.

---

## Startup

```bash
cd /home/pi/benchagent
source venv/bin/activate
uvicorn worker:app --host 0.0.0.0 --port 8420
```

On boot: systemd service (optional, nice to have for demo reliability).

## Dependencies

```
fastapi
uvicorn
dwfpy>=1.1.0
pyserial
matplotlib
numpy
```

Plus the `dps150` library installed from `~/work/galois/dps150` via `pip install -e`.
