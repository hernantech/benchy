# BenchCI — Architecture Report & Merge Plan

> **Hackathon: Vercel × DeepMind — March 21, 2026**
> **Time remaining: ~3 hours**

---

## 1. How the Existing Firmware Works

### Two-Board Architecture

BenchCI uses **two ESP32-S3 boards** working in tandem:

| Board | Role | Serial Port | Key Capabilities |
|-------|------|-------------|------------------|
| **DUT** (Device Under Test) | Runs the firmware being tested | `/dev/ttyACM0` | PWM, I2C master, UART, CAN/TWAI, GPIO, ADC, WiFi |
| **Fixture** (Test Partner) | Observes, stimulates, and resets the DUT | `/dev/ttyACM1` | I2C slave, DUT reset (GPIO 7 → DUT EN), load injection (MOSFET on GPIO 4), UART relay |

### Command Interface

Both boards accept **newline-delimited JSON commands** over USB serial at 115200 baud:

```
→  {"cmd":"pwm","pin":4,"freq":1000,"duty":50}
←  {"ok":true,"cmd":"pwm","pin":4,"channel":0,"freq":1000,"duty_pct":50,"duty_raw":512}
```

The DUT supports ~40 commands covering all ESP32-S3 peripherals. The fixture adds specialized commands for I2C slave emulation (`i2c_slave_init`, `i2c_slave_set_resp`, `i2c_slave_set_mode`), DUT reset control (`reset_dut`), and load injection (`load`).

### Boot Sequence

On power-up, each board announces itself:
```json
{"event":"boot","board":"dut","chip":"ESP32-S3","fw":"benchci-dut","ver":"0.1.0"}
```

The RPi worker uses this to auto-discover which USB port maps to which board.

### Firmware Build System

Both projects use **PlatformIO** with Arduino framework on `esp32-s3-devkitc-1`. Build and flash:
```bash
cd firmware/dut && pio run -t upload --upload-port /dev/ttyACM0
cd firmware/fixture && pio run -t upload --upload-port /dev/ttyACM1
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
         │                              │
         └──── USB ────── RPi 5 ──── USB ───┘
                           │
                     ┌─────┴─────┐
                     │ DPS-150   │  (Power Supply)
                     │ Analog    │  (Oscilloscope)
                     │ Discovery │
                     └───────────┘
```

---

## 2. Current System Components

### Benchy (the main repo)

| Component | Status | What it does |
|-----------|--------|-------------|
| `firmware/dut/` | **Complete** | JSON command interface for all ESP32 peripherals |
| `firmware/fixture/` | **Complete** | I2C slave, DUT reset, load injection |
| `edge/worker.py` | **Complete** | FastAPI on RPi 5 — PSU, scope, serial bridge, protocol decoders, chart rendering |
| `frontend/` (Next.js 16) | **Partial** | Agent chat page with Gemini tool-calling, run list UI, waveform chart component |
| `PI_WORKER_SPEC.md` | **Complete** | Full API documentation |

**Benchy's agent** (`/api/agent/route.ts`) already has 5 tools wired to Gemini:
- `set_psu` → `/psu/configure`
- `capture_scope` → `/scope/capture`
- `dut_command` → `/esp32/a/serial/send`
- `fixture_command` → `/esp32/b/serial/send`
- `sweep_voltage` → `/psu/sweep`

### vercelXdeepmind (the hackathon MVP)

| Component | Status | What it does |
|-----------|--------|-------------|
| `apps/web/` (Next.js 15) | **Working MVP** | Port detection, job trigger, live polling, log viewer |
| `services/hardware-runner/` | **Working MVP** | Flash via esptool, serial monitor, deterministic pass/fail |
| `firmware/led_blink_mvp/` | **Working** | Prebuilt binary, marker-based verification |
| Phase 2 stubs | **Stub** | `/run-can-demo`, `/capture-instrument`, `/analyze-artifacts` |

**Key things vercelXdeepmind has that benchy doesn't:**
- Working esptool flashing adapter (`esptool_adapter.py`)
- Serial monitoring with timeout and early-exit (`serial_adapter.py`)
- Deterministic evaluation engine (`evaluation.py`)
- Job lifecycle management with persistence (`job_store.py`, `runner.py`)
- Job status polling UI with timeline visualization
- Prebuilt firmware binary delivery

**Key things vercelXdeepmind lacks:**
- No AI/LLM integration (purely deterministic)
- No instrument control (no scope, no PSU)
- No fixture board support
- Single firmware profile only (led_blink_mvp)
- No dynamic firmware generation or compilation

---

## 3. The Vision: Autonomous Firmware Development Loop

```
┌─────────────────────────────────────────────────────────────┐
│                     USER INTERFACE                           │
│  1. Select board (ESP32-S3, ESP32-C3, etc.)                │
│  2. Describe test OR pick from suggested tests              │
│  3. Watch autonomous loop execute                           │
│  4. Receive final report                                    │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   AI AGENT (Gemini)                          │
│                                                             │
│  ┌─── PLAN ──────────────────────────────────────────────┐  │
│  │ Parse user intent → Select test template →             │  │
│  │ Generate firmware code → Define pass criteria          │  │
│  └───────────────────────────────────────────────────────┘  │
│                       │                                      │
│                       ▼                                      │
│  ┌─── EXECUTE ───────────────────────────────────────────┐  │
│  │ Compile firmware → Flash to DUT → Configure fixture → │  │
│  │ Set PSU voltage → Run test sequence → Capture scope → │  │
│  │ Read serial output → Collect measurements             │  │
│  └───────────────────────────────────────────────────────┘  │
│                       │                                      │
│                       ▼                                      │
│  ┌─── ANALYZE ───────────────────────────────────────────┐  │
│  │ Compare results to expectations →                      │  │
│  │ If FAIL: diagnose from scope waveforms + serial logs → │  │
│  │ Revise firmware code → Go back to EXECUTE              │  │
│  │ If PASS: Generate report                               │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  Max iterations: 5 (prevent infinite loops)                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Gap Analysis — What's Missing

### Critical Path (must have for demo)

| # | Gap | Where it lives today | What needs to happen | Effort |
|---|-----|---------------------|---------------------|--------|
| 1 | **Dynamic firmware generation** | Neither repo | LLM generates C++ from test description + board spec | New: agent prompt + code generation tool |
| 2 | **Dynamic firmware compilation** | vercelXdeepmind has esptool flash only | RPi worker needs `pio run` build step before flash | Add `/firmware/compile` endpoint to worker |
| 3 | **Flash from generated binary** | vercelXdeepmind `esptool_adapter.py` | Port esptool adapter into benchy's worker, or add flash endpoint | Merge adapter into `edge/worker.py` |
| 4 | **Board selection UI** | Neither repo | Dropdown/input for board type, feeds into LLM context | Frontend component |
| 5 | **Test suggestion engine** | Neither repo | Predefined test templates per board + LLM suggestion | JSON test catalog + agent prompt |
| 6 | **Autonomous retry loop** | Neither repo | Agent detects failure from scope/serial → revises code → re-flashes | Agent loop logic in `/api/agent/route.ts` |
| 7 | **Structured report generation** | Neither repo | After pass or max retries, generate markdown/PDF report | Agent final step + report template |
| 8 | **Job persistence & history** | vercelXdeepmind `job_store.py` | Port job model into benchy or use Supabase | Merge or new |

### Nice to Have (if time permits)

| # | Gap | Effort |
|---|-----|--------|
| 9 | Supabase realtime for live updates (replace polling) | Medium |
| 10 | Waveform chart rendering in frontend (recharts) | Already stubbed |
| 11 | Multi-board support (ESP32-C3, C6, etc.) | PlatformIO board config |
| 12 | MicroPython support (faster iteration, no compile step) | Alternative path |

---

## 5. Proposed Architecture for Merged System

### System Diagram

```
┌──────────────────────────────────────────────────────────────┐
│ VERCEL / NEXT.JS 16                                          │
│                                                              │
│  ┌─────────────┐  ┌──────────────────┐  ┌───────────────┐  │
│  │ / (Home)    │  │ /agent (Chat)    │  │ /reports      │  │
│  │ Board select│  │ AI conversation  │  │ Past test     │  │
│  │ Test picker │  │ Live status      │  │ reports       │  │
│  │ Run trigger │  │ Waveform charts  │  │               │  │
│  └──────┬──────┘  └───────┬──────────┘  └───────────────┘  │
│         │                 │                                   │
│  ┌──────┴─────────────────┴──────────────────────────────┐  │
│  │ /api/agent/route.ts — Gemini 2.0 Flash Agent          │  │
│  │                                                        │  │
│  │ Tools:                                                 │  │
│  │  generate_firmware  — LLM writes C++ for test goal     │  │
│  │  compile_firmware   — POST /firmware/compile           │  │
│  │  flash_firmware     — POST /esp32/{id}/flash           │  │
│  │  dut_command        — POST /esp32/a/serial/send        │  │
│  │  fixture_command    — POST /esp32/b/serial/send        │  │
│  │  set_psu            — POST /psu/configure              │  │
│  │  capture_scope      — POST /scope/capture              │  │
│  │  sweep_voltage      — POST /psu/sweep                  │  │
│  │  measure_signal     — POST /scope/signal_integrity     │  │
│  │  evaluate_run       — deterministic marker check       │  │
│  │  generate_report    — compile results into report      │  │
│  └───────────────────────┬───────────────────────────────┘  │
│                          │ HTTP over Tailscale               │
└──────────────────────────┼───────────────────────────────────┘
                           │
┌──────────────────────────┴───────────────────────────────────┐
│ RPi 5 — EDGE WORKER (FastAPI :8420)                          │
│                                                              │
│  EXISTING ENDPOINTS         NEW ENDPOINTS                    │
│  ├─ /health                 ├─ /firmware/compile             │
│  ├─ /psu/*                  │   (pio run, returns .bin path) │
│  ├─ /scope/*                ├─ /firmware/write               │
│  ├─ /esp32/{id}/serial/*    │   (write generated C++ to disk)│
│  ├─ /esp32/{id}/reset       ├─ /esp32/{id}/flash             │
│  ├─ /uart/capture           │   (esptool flash from .bin)    │
│  ├─ /run/debug              ├─ /jobs/* (lifecycle mgmt)      │
│  └─ /run/benchmark          └─ /reports/* (store & serve)    │
│                                                              │
│  USB Devices:                                                │
│  ├─ DPS-150 PSU                                              │
│  ├─ Analog Discovery (scope + logic analyzer)                │
│  ├─ ESP32-S3 DUT (/dev/ttyACM0)                             │
│  └─ ESP32-S3 Fixture (/dev/ttyACM1)                         │
└──────────────────────────────────────────────────────────────┘
```

### Agent Loop (Core Innovation)

```python
# Pseudocode for the autonomous loop

async def autonomous_test_loop(board: str, test_description: str):
    MAX_ITERATIONS = 5

    # Step 1: Generate initial firmware
    code = await llm_generate_firmware(board, test_description)
    pass_criteria = await llm_define_pass_criteria(test_description)

    for iteration in range(MAX_ITERATIONS):
        # Step 2: Write firmware to disk on RPi
        await rpi.post("/firmware/write", {
            "path": f"firmware/generated/src/main.cpp",
            "content": code,
            "board": board
        })

        # Step 3: Compile
        build = await rpi.post("/firmware/compile", {
            "project": "firmware/generated",
            "board": board
        })
        if not build.ok:
            code = await llm_fix_compile_error(code, build.errors)
            continue

        # Step 4: Flash
        await rpi.post(f"/esp32/a/flash", {"binary": build.binary_path})

        # Step 5: Configure test environment
        await rpi.post("/psu/configure", {"voltage": 3.3, "current": 0.5, "output": True})
        await rpi.post("/esp32/b/serial/send", {"cmd": "reset_dut"})

        # Step 6: Run test + capture data
        scope_data = await rpi.post("/scope/capture", {"channel": 1, "duration_ms": 2000})
        serial_log = await rpi.post("/esp32/a/serial/read", {"timeout_ms": 5000})
        psu_state = await rpi.get("/psu/state")

        # Step 7: Evaluate
        verdict = evaluate_markers(serial_log, pass_criteria)

        if verdict.passed:
            return await generate_report(
                iteration, code, scope_data, serial_log, psu_state, "PASSED"
            )

        # Step 8: Diagnose & revise
        diagnosis = await llm_diagnose_failure(
            code=code,
            serial_log=serial_log,
            scope_waveform=scope_data.chart_url,
            psu_state=psu_state,
            error=verdict.reason
        )
        code = await llm_revise_firmware(code, diagnosis)

    return await generate_report(MAX_ITERATIONS, code, scope_data, serial_log, psu_state, "MAX_RETRIES")
```

### New Agent Tools Definition

```typescript
// Added to /api/agent/route.ts

const NEW_TOOLS = {
  generate_firmware: {
    description: "Generate ESP32 C++ firmware code for a specific test goal. " +
      "Returns compilable Arduino/PlatformIO code.",
    parameters: {
      board: "Target board (esp32-s3-devkitc-1, esp32-c3-devkitm-1, etc.)",
      goal: "What the firmware should do (e.g., 'generate 1kHz PWM on GPIO4')",
      constraints: "Any constraints (e.g., 'must print MVP_PASS when done')"
    }
  },
  compile_firmware: {
    description: "Compile firmware source code on the RPi using PlatformIO. " +
      "Returns success/failure and any compiler errors.",
    parameters: {
      source_code: "The C++ source code to compile",
      board: "PlatformIO board identifier"
    }
  },
  flash_firmware: {
    description: "Flash compiled firmware binary to the DUT ESP32 board.",
    parameters: {
      binary_path: "Path to .bin file on RPi (from compile step)"
    }
  },
  evaluate_run: {
    description: "Check serial output against expected markers. " +
      "Returns pass/fail with reason.",
    parameters: {
      serial_log: "Array of serial output lines",
      expected_markers: "Ordered list of strings that must appear"
    }
  },
  generate_report: {
    description: "Compile all test data into a structured report.",
    parameters: {
      iterations: "Number of attempts",
      final_code: "Final firmware source",
      measurements: "Scope, PSU, serial data",
      verdict: "PASSED or FAILED with reason"
    }
  }
};
```

### New RPi Worker Endpoints

```python
# Added to edge/worker.py

@app.post("/firmware/write")
async def write_firmware(req: FirmwareWriteRequest):
    """Write LLM-generated source code to disk."""
    path = FIRMWARE_DIR / req.project / "src" / "main.cpp"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(req.content)

    # Also write platformio.ini if needed
    ini_path = FIRMWARE_DIR / req.project / "platformio.ini"
    if not ini_path.exists():
        ini_path.write_text(generate_platformio_ini(req.board))

    return {"ok": True, "path": str(path)}


@app.post("/firmware/compile")
async def compile_firmware(req: CompileRequest):
    """Compile firmware using PlatformIO CLI."""
    project_dir = FIRMWARE_DIR / req.project
    result = subprocess.run(
        ["pio", "run", "-d", str(project_dir)],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        return {"ok": False, "errors": result.stderr}

    bin_path = project_dir / ".pio" / "build" / req.env / "firmware.bin"
    return {"ok": True, "binary_path": str(bin_path)}


@app.post("/esp32/{board_id}/flash")
async def flash_esp32(board_id: str, req: FlashRequest):
    """Flash compiled binary to ESP32 using esptool."""
    port = _get_port(board_id)
    result = subprocess.run(
        ["esptool.py", "--chip", "esp32s3", "--port", port,
         "--baud", "460800", "write_flash", "--flash_mode", "dio",
         "--flash_size", "detect", "0x0", req.binary_path],
        capture_output=True, text=True, timeout=60
    )
    return {"ok": result.returncode == 0, "output": result.stdout + result.stderr}
```

---

## 6. What to Build in 3 Hours — Prioritized Sprint Plan

### Hour 1: Core Pipeline (Compile → Flash → Monitor)

**1.1 Add `/firmware/write` and `/firmware/compile` to `edge/worker.py`** (30 min)
- Accept source code string + board type
- Write to `/tmp/benchci/generated/src/main.cpp`
- Generate `platformio.ini` from board type
- Run `pio run`, return success + binary path or errors

**1.2 Add `/esp32/{id}/flash` to `edge/worker.py`** (15 min)
- Port `esptool_adapter.py` from vercelXdeepmind
- Accept binary path, flash to correct serial port
- Return success/failure with esptool output

**1.3 Add serial monitoring with markers** (15 min)
- Port `serial_adapter.py` monitoring logic (timeout + early exit on pass marker)
- Port `evaluation.py` deterministic verdict logic
- Add to existing `/esp32/{id}/serial/read` or new `/esp32/{id}/monitor` endpoint

### Hour 2: AI Agent Loop

**2.1 Update agent route with new tools** (30 min)
- Add `generate_firmware`, `compile_firmware`, `flash_firmware`, `evaluate_run` tools
- Wire each tool to corresponding RPi endpoint
- Add system prompt instructing Gemini on the autonomous loop:
  ```
  You are BenchCI, an autonomous firmware test agent.
  When the user describes a test:
  1. Generate C++ firmware code for the target board
  2. Compile it on the RPi
  3. Flash it to the DUT
  4. Configure instruments (PSU, scope)
  5. Run the test and capture results
  6. If it fails, analyze scope waveforms and serial logs to diagnose
  7. Revise the firmware and try again (max 5 attempts)
  8. Generate a final report
  ```

**2.2 Board selection + test suggestion UI** (30 min)
- Add board selector dropdown on home page (ESP32-S3, ESP32-C3, etc.)
- Add test suggestion cards (brownout threshold, PWM verification, I2C stress test, etc.)
- "Custom test" text input
- On submit → navigate to `/agent` with context pre-filled

### Hour 3: Polish & Demo

**3.1 Report generation** (20 min)
- Agent tool that formats: iterations, final code, measurements, waveform PNGs, verdict
- Display as structured card in chat UI

**3.2 Test catalog** (15 min)
- JSON file with 5-8 pre-built test templates:
  ```json
  [
    {
      "id": "brownout-sweep",
      "name": "Brownout Threshold Finder",
      "description": "Sweep supply voltage from 3.6V to 2.0V, find minimum stable voltage",
      "board": "esp32-s3-devkitc-1",
      "instruments": ["psu", "scope"],
      "suggested_firmware": "Boot loop with serial heartbeat"
    },
    {
      "id": "pwm-verify",
      "name": "PWM Accuracy Test",
      "description": "Generate PWM at target frequency/duty, verify with oscilloscope",
      "board": "esp32-s3-devkitc-1",
      "instruments": ["scope"]
    }
  ]
  ```

**3.3 End-to-end demo run** (25 min)
- Run through the full loop: select board → pick test → agent generates code → compiles → flashes → captures scope → evaluates → report
- Fix any integration issues
- Record demo if needed

---

## 7. File-Level Merge Plan

### Files to port FROM vercelXdeepmind INTO benchy:

| Source (vercelXdeepmind) | Destination (benchy) | Action |
|--------------------------|---------------------|--------|
| `services/hardware-runner/app/adapters/esptool_adapter.py` | `edge/worker.py` (integrate) | Merge flash logic into existing worker |
| `services/hardware-runner/app/adapters/serial_adapter.py` | `edge/worker.py` (integrate) | Merge monitor logic (DTR reset, timeout, early exit) |
| `services/hardware-runner/app/services/evaluation.py` | `edge/worker.py` or `frontend/src/lib/evaluation.ts` | Port marker-based verdict (can be server or client side) |
| `services/hardware-runner/app/services/runner.py` | Agent loop in `/api/agent/route.ts` | The agent replaces the runner — LLM orchestrates the steps |
| `services/hardware-runner/app/services/job_store.py` | Supabase or `edge/worker.py` | Job persistence |
| `apps/web/app/components/LogViewer.tsx` | `frontend/src/components/log-viewer.tsx` | Direct port — colored serial log display |
| `apps/web/app/components/JobCard.tsx` | `frontend/src/components/job-card.tsx` | Adapt for agent-driven jobs |

### Files to CREATE in benchy:

| File | Purpose |
|------|---------|
| `frontend/src/lib/test-catalog.json` | Pre-built test templates |
| `frontend/src/components/board-selector.tsx` | Board type picker |
| `frontend/src/components/test-picker.tsx` | Test suggestion cards + custom input |
| `frontend/src/components/report-view.tsx` | Structured test report display |
| `edge/firmware_templates/platformio.ini.tmpl` | Template for generated projects |

### Files to MODIFY in benchy:

| File | Changes |
|------|---------|
| `edge/worker.py` | Add `/firmware/write`, `/firmware/compile`, `/esp32/{id}/flash`, `/esp32/{id}/monitor` |
| `frontend/src/app/api/agent/route.ts` | Add new tools, update system prompt for autonomous loop |
| `frontend/src/app/page.tsx` | Add board selector, test picker, connect to agent |
| `frontend/src/app/agent/page.tsx` | Show waveform charts, log viewer, report view inline |
| `frontend/src/lib/types.ts` | Add Job, TestTemplate, Report types |

---

## 8. Key Design Decisions

### Why the LLM replaces the runner (not wraps it)

In vercelXdeepmind, `runner.py` is a hardcoded sequential pipeline: flash → monitor → evaluate. In the merged system, **Gemini IS the runner** — it decides what to do based on results. The deterministic evaluation from `evaluation.py` becomes one tool the agent can call, not the orchestrator.

### Why compile on the RPi (not Vercel)

PlatformIO requires the ESP-IDF toolchain (~2GB). The RPi already has it for the existing firmware. Compiling on Vercel serverless is impractical (cold start, toolchain size, no USB). The RPi worker is the right place.

### Why Gemini generates C++ (not MicroPython)

The existing DUT firmware is C++/Arduino. PlatformIO is already set up. C++ gives full peripheral access and matches the existing codebase. MicroPython could be a future option for faster iteration (no compile step) but adds deployment complexity.

### Why max 5 iterations

Prevents runaway loops. Each iteration involves compile (~30s) + flash (~15s) + test (~5s) + scope capture (~2s). Five iterations = ~4 minutes max, which fits the demo window.

---

## 9. Demo Script (3-Minute Flow)

1. **Open BenchCI** → Show board selector, pick "ESP32-S3 DevKitC-1"
2. **Pick test** → "PWM Accuracy Test" or type custom: "Generate 1kHz PWM on GPIO4, verify with scope"
3. **Agent starts** → Shows plan: "I'll generate firmware, flash it, and verify the PWM output"
4. **Iteration 1** → Agent generates code, compiles (show build output), flashes (show progress), captures scope waveform (show PNG), reads serial. Suppose duty cycle is off — agent says "Duty cycle measured at 30% instead of 50%, adjusting LEDC configuration"
5. **Iteration 2** → Revised code, re-flash, re-capture. Now waveform shows correct 1kHz 50% duty. "PASS"
6. **Report** → Shows structured report: board, test, iterations, final code, waveform chart, measurements, verdict

---

## 10. Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| PlatformIO not installed on RPi | Pre-install before demo; add check in `/health` |
| esptool flash fails | Fallback: use pre-compiled binaries for demo tests |
| LLM generates uncompilable code | Compile errors fed back to LLM; max retry limit |
| Scope capture timing misaligned | Use generous capture windows (2-5 seconds) |
| Tailscale connection drops | Test connection before demo; have local fallback |
| 3 hours too tight | Priority: get compile→flash→monitor loop working first, AI loop second, polish last |
