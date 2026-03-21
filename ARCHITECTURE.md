# BenchCI — Architecture

> AI agent that controls real lab instruments to test, diagnose, and fix hardware autonomously.

---

## System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│ iPhone (Flutter iOS app)                                         │
│   Streams JPEG @ 10fps over Tailscale WebSocket                  │
└────────────────────┬─────────────────────────────────────────────┘
                     │ ws://benchagent-pi:8420/camera/ws
                     ▼
┌──────────────────────────────────────────────────────────────────┐
│ RPi 5 — Edge Worker (FastAPI, port 8420)                         │
│                                                                  │
│  Instruments (USB):                                              │
│  ├── DPS-150 PSU         (0–5.5V, 0–1.0A, programmable)         │
│  ├── Analog Discovery 2  (2ch scope, logic analyzer, decoders)  │
│  ├── ESP32-S3 DUT        (/dev/ttyACM0, device under test)      │
│  └── ESP32-S3 Fixture    (/dev/ttyACM1, test partner)           │
│                                                                  │
│  Modules:                                                        │
│  ├── worker.py           (1332 lines — all instrument endpoints) │
│  └── rca/                (Root Cause Analysis pipeline)          │
│      ├── signal_processing.py   Tier 1: EE math (FFT, rise      │
│      │                          time, ripple, CAN levels)        │
│      ├── context_analyzer.py    Tier 2: hypothesis generation    │
│      │                          with ESP32-S3 board knowledge    │
│      ├── orchestrator.py        Session management + pipeline    │
│      ├── report.py              Structured report generation     │
│      ├── rca_endpoints.py       FastAPI router (/rca/*)          │
│      └── simulated_test.py      6/6 verification scenarios       │
└────────────────────┬─────────────────────────────────────────────┘
                     │ HTTP over Tailscale (no auth, ACL-secured)
                     ▼
┌──────────────────────────────────────────────────────────────────┐
│ Vercel — Next.js 16 (React 19, TypeScript)                       │
│                                                                  │
│  Layout: 3-column (VS Code style)                                │
│  ┌──────────┬────────────────────┬──────────────┐               │
│  │ Run List │   Run Detail       │  Agent Chat  │               │
│  │ (w-72)   │   (flex-1)         │  (w-400px)   │               │
│  └──────────┴────────────────────┴──────────────┘               │
│                                                                  │
│  /api/agent/route.ts — Gemini 3.1 Pro with 21 tools              │
│  /api/runs/route.ts  — Run management (stub)                     │
└──────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
benchy/
├── ARCHITECTURE.md              ← this file
├── PI_WORKER_SPEC.md            API reference for edge worker
├── RCA_DESIGN.md                RCA pipeline design doc
├── docker-compose.yml           Docker compose for frontend
├── .firebaserc                  Firebase hosting config
│
├── docs/
│   ├── WIRING_CHEATSHEET.md               Quick GPIO map for DUT + fixture
│   └── ESP32-S3-DevKitC-1-U-WIRING-REFERENCE.md   Full pinout, safety, strapping
│
├── firmware/
│   ├── dut/                     Device Under Test (PlatformIO + Arduino)
│   │   ├── platformio.ini
│   │   └── src/main.cpp         ~694 lines, ~40 JSON command handlers
│   └── fixture/                 Test Partner
│       ├── platformio.ini
│       └── src/main.cpp         ~718 lines, I2C slave, reset, load inject
│
├── edge/
│   ├── worker.py                1332 lines — FastAPI server, all endpoints
│   └── rca/                     Root Cause Analysis module
│       ├── __init__.py
│       ├── signal_processing.py Tier 1: deterministic EE calculations
│       ├── context_analyzer.py  Tier 2: rule-based hypothesis generation
│       ├── orchestrator.py      Session management, pipeline runner
│       ├── report.py            Report generation (dict + markdown)
│       ├── rca_endpoints.py     FastAPI router mounted at /rca/*
│       └── simulated_test.py    6 verification scenarios (all pass)
│
├── frontend/                    Next.js 16.2.1
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx       Nav: "benchy" logo, Runs, Instruments
│   │   │   ├── page.tsx         3-column: RunList | RunDetail | AgentChat
│   │   │   ├── agent/page.tsx   Standalone agent page (legacy)
│   │   │   ├── instruments/page.tsx  Instrument status (stub)
│   │   │   └── api/
│   │   │       ├── agent/route.ts   Gemini 3.1 Pro, 21 tools
│   │   │       └── runs/route.ts    Run CRUD (stub)
│   │   ├── components/
│   │   │   ├── agent-chat.tsx   Chat UI with markdown, tool calls, suggestions
│   │   │   ├── run-detail.tsx   Run detail with steps, measurements, diagnosis
│   │   │   ├── run-list.tsx     Sidebar run selector with status badges
│   │   │   └── waveform-chart.tsx  Recharts scope visualization
│   │   └── lib/
│   │       ├── runner.ts        HTTP client for RPi worker (203 lines)
│   │       ├── types.ts         Run, RunStep, Measurement, Diagnosis, etc.
│   │       ├── supabase.ts      Supabase client (stub)
│   │       └── mock-data.ts     Mock runs and steps for UI development
│   └── package.json
│
├── mobile/                      Flutter iOS camera app
│   ├── lib/main.dart            369 lines — JPEG stream to RPi WebSocket
│   ├── pubspec.yaml
│   └── ios/                     Xcode project
│
├── pipeline/                    LangGraph firmware optimization
│   └── pipeline/
│       ├── main.py              Entry point
│       ├── state.py             Graph state definitions
│       ├── graphs.py            LangGraph graph definitions
│       ├── callbacks.py         Execution callbacks
│       ├── runner_client.py     Client for RPi worker
│       └── nodes/               14 node files
│           ├── debug_*.py       4 nodes: setup, capture, diagnose, fix
│           ├── firmware_*.py    5 nodes: architect, generate, compile, stitch, flash_test
│           └── optimize_*.py    5 nodes: generate, benchmark, analyze, compare
│
└── supabase/
    └── migrations/              Database schema
```

---

## Firmware

### Two-Board Architecture

| Board | Role | Port | Capabilities |
|-------|------|------|-------------|
| **DUT** | Device Under Test | `/dev/ttyACM0` | PWM (8ch LEDC), I2C master, UART, CAN/TWAI, GPIO, ADC, WiFi |
| **Fixture** | Test Partner | `/dev/ttyACM1` | I2C slave emulation, DUT reset (GPIO 7 → EN), load injection (MOSFET GPIO 4), UART relay |

### Command Protocol

Newline-delimited JSON over USB serial at 115200 baud:

```
→  {"cmd":"pwm","pin":4,"freq":1000,"duty":50}
←  {"ok":true,"cmd":"pwm","pin":4,"channel":0,"freq":1000,"duty_pct":50,"duty_raw":512}
```

On boot, each board announces itself with `{"event":"boot","board":"dut"|"fixture",...}`. The RPi worker uses this to auto-discover port mapping.

### Build System

PlatformIO with Arduino framework on `esp32-s3-devkitc-1`:
```bash
cd firmware/dut && pio run -t upload --upload-port /dev/ttyACM0
```

### Hardware Wiring

```
DUT ESP32-S3                    Fixture ESP32-S3
┌──────────┐                    ┌──────────┐
│ GPIO 8 (SDA) ──────────────── GPIO 8 (SDA) │
│ GPIO 9 (SCL) ──────────────── GPIO 9 (SCL) │
│ GPIO 17 (TX) ──────────────── GPIO 18 (RX) │
│ GPIO 5 (CAN TX) ────────────── GPIO 6 (CAN RX) │
│ GPIO 6 (CAN RX) ────────────── GPIO 5 (CAN TX) │
│ EN pin ──────────────────────── GPIO 7       │
│ VIN ─────────────── MOSFET ──── GPIO 4       │
└──────────┘                    └──────────┘
```

Full wiring reference in `docs/ESP32-S3-DevKitC-1-U-WIRING-REFERENCE.md`.

---

## Edge Worker (RPi 5)

**File:** `edge/worker.py` (1332 lines)
**Port:** 8420, accessed over Tailscale from Vercel

### All Endpoints

| Group | Endpoint | Method | Purpose |
|-------|----------|--------|---------|
| **Health** | `/health` | GET | Connected instrument status |
| | `/capabilities` | GET | Full tool catalog with parameters |
| **PSU** | `/psu/configure` | POST | Set voltage (0–5.5V), current (0–1.0A), enable |
| | `/psu/state` | GET | Live telemetry (V, I, P, mode, temp) |
| | `/psu/sweep` | POST | Voltage sweep with per-step measurements |
| | `/psu/off` | POST | Safety kill switch |
| **Scope** | `/scope/capture` | POST | Waveform acquisition + PNG chart + stats |
| | `/scope/measure` | POST | Single DC/RMS/frequency measurement |
| | `/scope/pulse_width` | POST | GPIO timing measurement |
| | `/scope/signal_integrity` | POST | Rise/fall time, overshoot/undershoot |
| **Protocol** | `/uart/capture` | POST | Capture UART data from DIO pin |
| | `/i2c/capture` | POST | Capture I2C transactions |
| **ESP32** | `/esp32/{board}/serial/send` | POST | Send JSON command, get response |
| | `/esp32/{board}/serial/read` | POST | Read buffered serial output |
| | `/esp32/{board}/reset` | POST | Reset via fixture GPIO or DTR |
| | `/esp32/{board}/flash` | POST | Compile + flash via PlatformIO/esptool |
| **Compound** | `/run/debug` | POST | Full debug cycle: PSU + reset + scope + UART |
| | `/run/benchmark` | POST | Kernel benchmark with timing + power |
| **Camera** | `/camera/ws` | WS | Receive JPEG frames from phone |
| | `/camera/latest` | GET | Last captured frame |
| | `/camera/snapshot` | POST | Take photo from stream |
| | `/camera/analyze` | POST | Send frame to Gemini vision |
| | `/camera/status` | GET | Phone connection status |
| **Firmware** | `/firmware/write` | POST | Write generated source to disk |
| | `/firmware/compile` | POST | Compile with PlatformIO CLI |
| **RCA** | `/rca/session` | POST | Create RCA session |
| | `/rca/analyze` | POST | Run Tier 1 + Tier 2 analysis |
| | `/rca/report` | POST | Generate final RCA report |
| | `/rca/session/{id}` | GET | Get session state |
| | `/rca/sessions` | GET | List all sessions |
| **Artifacts** | `/artifacts/{filename}` | GET | Serve charts, CSVs, images |

### Safety Clamps

Hardcoded, non-negotiable:
- `PSU_MAX_VOLTAGE = 5.5V` (ESP32 VIN absolute max)
- `PSU_MAX_CURRENT = 1.0A`

---

## Gemini Agent

**File:** `frontend/src/app/api/agent/route.ts`
**Model:** `gemini-3.1-pro-preview` via `@ai-sdk/google`
**Max steps:** 15 per request

### All 21 Tools

| # | Tool | Calls | Purpose |
|---|------|-------|---------|
| 1 | `set_psu` | `/psu/configure` | Set voltage, current limit, enable output |
| 2 | `psu_off` | `/psu/off` | Safety kill switch |
| 3 | `capture_scope` | `/scope/capture` | Capture waveform, returns stats + chart URL |
| 4 | `measure_pulse_width` | `/scope/pulse_width` | GPIO timing measurement |
| 5 | `signal_integrity` | `/scope/signal_integrity` | Rise/fall time, overshoot analysis |
| 6 | `sweep_voltage` | `/psu/sweep` | Voltage sweep for brownout testing |
| 7 | `dut_command` | `/esp32/a/serial/send` | Send JSON command to DUT |
| 8 | `fixture_command` | `/esp32/b/serial/send` | Send JSON command to fixture |
| 9 | `run_debug` | `/run/debug` | Full debug cycle |
| 10 | `run_benchmark` | `/run/benchmark` | Firmware benchmark |
| 11 | `health_check` | `/health` | Instrument connection status |
| 12 | `get_capabilities` | `/capabilities` | Discover all bench commands |
| 13 | `wiring_reference` | local | Look up GPIO pinout, power, safety from docs |
| 14 | `camera_snapshot` | `/camera/snapshot` | Take photo from phone stream |
| 15 | `camera_analyze` | `/camera/analyze` | Send frame to Gemini vision |
| 16 | `camera_status` | `/camera/status` | Check if phone is streaming |
| 17 | `analyze_rca_start` | `/rca/session` | Create RCA session |
| 18 | `analyze_rca` | `/rca/analyze` | Feed measurements, get hypotheses |
| 19 | `analyze_rca_report` | `/rca/report` | Generate final RCA report |

Plus 2 undocumented internal tools (firmware write/compile) exposed through direct `runnerCall`.

### System Prompt Highlights

- Wiring cheatsheet and full reference loaded at startup from `docs/`
- Scope channels are 0-indexed (0=CH1, 1=CH2)
- ESP32-S3 is 3.3V logic — never set PSU above 3.6V on 3V3 pin directly
- PSU connects to VIN (regulator input), not 3.3V rail
- **User confirmation gate**: agent must wait for user to confirm wiring before energizing hardware
- RCA workflow: capture → analyze → diagnose → fix/probe → re-analyze → report

---

## Root Cause Analysis (RCA)

Three-tier analysis pipeline that closes the feedback loop between hardware measurements and diagnosis.

```
User ↔ Chat UI ↔ Gemini Agent (Tier 3 — decision maker)
                      ↓ tool call: analyze_rca
                  RPi Edge Worker
                      ↓
                  ┌──────────────────────────────┐
                  │ Tier 1: Signal Processing    │  deterministic EE math
                  │   voltage, ripple, FFT,      │  (numpy, no LLM)
                  │   rise time, CAN levels      │
                  ├──────────────────────────────┤
                  │ Tier 2: Context Analyzer     │  rule-based + board docs
                  │   ranked hypotheses,         │  (ESP32-S3 knowledge base)
                  │   evidence chains,           │
                  │   verification steps         │
                  └──────────────────────────────┘
                      ↓
                  Structured JSON → back to Gemini
```

### Tier 1 Metrics

**Voltage/Power Rail:** DC level, ripple (Vpp), RMS, dominant frequency (FFT), rise/fall time, overshoot/undershoot, settling time, slew rate

**CAN Bus:** Dominant V_diff, recessive V_diff, common-mode voltage, estimated bit rate

**PSU Telemetry:** Supply voltage, load current, power consumption

Each metric is compared against a `ThresholdSpec` → `PASS` / `WARN` / `FAIL` verdict.

### Tier 2 Hypothesis Categories

| Category | Example | Who Fixes |
|----------|---------|-----------|
| `power` | Regulator near current limit | PSU adjustment or hardware |
| `signal_integrity` | Impedance mismatch, ringing | Hardware (termination) |
| `protocol` | CAN/I2C bus errors | Firmware config or pull-ups |
| `firmware` | Brownout from WiFi current spike | Agent generates fix |
| `hardware` | Solder bridge, damaged component | User instructed |

### Confidence Flow

1. Per-metric hypotheses start at 10–50% confidence
2. Cross-metric correlations boost confidence (1.2× for merged hypotheses)
3. Serial log matches add independent hypotheses (40–50%)
4. Normalized to sum to 100%
5. If top hypothesis < 40% → LLM escalation prompt generated for Gemini

### Feedback Loop

```
[Measure] → scope/capture, psu/state, serial/read
    ↓
[Analyze] → /rca/analyze (Tier 1 + Tier 2)
    ↓
[Decide]  → Gemini agent (Tier 3)
    ├── Fix firmware → compile/flash → re-measure
    ├── Instruct user → hardware fix → re-measure
    ├── Probe more → different test point → re-measure
    └── Declare root cause → /rca/report

Max 5 iterations per session
```

Full design doc in `RCA_DESIGN.md`.

---

## Mobile Camera App

**Directory:** `mobile/`
**Framework:** Flutter (iOS)
**Entry:** `lib/main.dart` (369 lines)

Streams JPEG frames from the iPhone camera to the RPi worker over a Tailscale WebSocket:
- 10 FPS, JPEG quality 70
- Switchable front/back camera
- Connection status indicator
- The RPi stores the latest frame; the Gemini agent can call `camera_analyze` to send it to Gemini vision for wiring verification, probe placement checks, etc.

---

## LangGraph Pipeline

**Directory:** `pipeline/`
**Framework:** LangGraph (Python)

Three autonomous firmware optimization graphs with 14 node files:

| Pipeline | Nodes | Purpose |
|----------|-------|---------|
| **Debug** | setup → capture → diagnose → fix | Automated hardware debugging |
| **Firmware** | architect → generate → compile → stitch → flash_test | End-to-end firmware generation |
| **Optimize** | generate → benchmark → analyze → compare | Firmware performance optimization |

Uses `runner_client.py` to call the same RPi worker endpoints as the Gemini agent.

---

## Frontend

**Framework:** Next.js 16.2.1, React 19, TypeScript
**Styling:** Tailwind CSS 4, IBM Plex Sans/Mono fonts, OKLCH color system
**AI SDK:** `@ai-sdk/google` v3 + Vercel AI SDK v6 (tool calling)

### Layout

3-column layout (VS Code / Cursor style):

| Column | Width | Component | Content |
|--------|-------|-----------|---------|
| Left | 288px | `<RunList>` | Test run list with status badges, "New Run" button |
| Center | flex-1 | `<RunDetail>` | Selected run: steps timeline, measurements, waveform chart, AI diagnosis |
| Right | 400px | `<AgentChat>` | Chat with Gemini agent, suggested prompts, tool call display |

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `next` | 16.2.1 | React framework (App Router) |
| `react` | 19.2.4 | UI |
| `@ai-sdk/google` | ^3.0.52 | Gemini 3.1 Pro integration |
| `ai` | ^6.0.134 | Vercel AI SDK (tool calling) |
| `@supabase/supabase-js` | ^2.99.3 | Database (optional) |
| `recharts` | ^3.8.0 | Waveform chart visualization |
| `react-markdown` | ^10.1.0 | Render markdown in agent responses |
| `tailwindcss` | ^4 | Styling |

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Next.js 16, React 19, TypeScript, Tailwind 4 |
| **AI Agent** | Gemini 3.1 Pro via Vercel AI SDK v6 (21 tools) |
| **Edge Backend** | Python FastAPI + uvicorn on RPi 5 |
| **Camera Vision** | Gemini 3.1 Flash Lite (via RPi → Gemini API) |
| **RCA Pipeline** | NumPy (signal processing) + rule engine (Python) |
| **Firmware** | Arduino/ESP-IDF on ESP32-S3 (PlatformIO) |
| **Instruments** | dwfpy (AD2), dps150 lib, pyserial |
| **Mobile** | Flutter (iOS), Dart |
| **Pipelines** | LangGraph (Python) |
| **Database** | Supabase (PostgreSQL) — schema defined, integration in progress |
| **Networking** | Tailscale VPN (Vercel ↔ RPi ↔ Phone) |
| **Hosting** | Vercel (frontend), Firebase (optional), RPi 5 (edge) |
| **Charts** | Matplotlib (headless, RPi), Recharts (frontend) |

---

## Key Design Decisions

### Gemini IS the orchestrator

There is no separate orchestration layer. The Gemini agent in the chat UI decides what to do based on tool results. The RCA pipeline, firmware compilation, and instrument control are all tools the agent calls. The user talks directly to the decision maker.

### Compile on the RPi, not Vercel

PlatformIO requires the ESP-IDF toolchain (~2GB). The RPi already has it and has USB access to the boards. Vercel serverless can't do this (cold start, no USB, toolchain size).

### Three-tier RCA (not all-LLM)

Tier 1 (signal processing) and Tier 2 (hypothesis generation) are deterministic. Only Tier 3 (decision making) uses the LLM. This is faster, cheaper, and more reliable than sending raw waveform data to Gemini.

### User confirmation gate

The agent must wait for user confirmation before energizing hardware or changing physical state. This is enforced in the system prompt, not in code. The PSU connects to VIN (regulator input) — never directly to the 3.3V rail.

### Camera through the RPi (not direct)

The phone streams video to the RPi over Tailscale. The RPi stores the latest frame. When the agent needs to see the bench, it calls `camera_analyze` which sends the frame from the RPi to Gemini vision. This avoids the phone needing to talk to Vercel directly and keeps all instrument access on the RPi.
