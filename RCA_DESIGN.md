# Root Cause Analysis (RCA) — Design Document

> Guide for a Claude Code session to implement and extend the RCA feature in BenchCI.

## Overview

The RCA system is a three-tier analysis pipeline that closes the feedback loop between hardware measurements and actionable diagnosis. Raw oscilloscope waveforms, CAN bus captures, and PSU telemetry flow through deterministic signal processing, then rule-based hypothesis generation, and finally reach the Gemini chat agent — which acts as the decision-making orchestrator visible to the user.

```
User ↔ Chat UI ↔ Gemini Agent (Tier 3 — THE decision maker)
                      ↓ tool call: analyze_rca
                  RPi Edge Worker
                      ↓
                  ┌──────────────────────────────┐
                  │ Tier 1: Signal Processing    │  ← deterministic EE math
                  │   voltage, ripple, FFT,      │
                  │   rise time, CAN levels, etc │
                  ├──────────────────────────────┤
                  │ Tier 2: Context Analyzer     │  ← rule-based + board docs
                  │   ranked hypotheses,         │
                  │   evidence chains,           │
                  │   verification steps         │
                  └──────────────────────────────┘
                      ↓
                  Structured JSON → back to Gemini
                      ↓
                  Gemini decides: probe more, fix firmware,
                  instruct user, or declare root cause
```

**Key architectural decision:** The Gemini chat agent IS Tier 3. There is no separate orchestrator agent. Tier 1 + Tier 2 are server-side processing that feed the chat agent structured analysis results as tool responses. The user talks to Gemini, and Gemini uses RCA analysis as one of its tools.

---

## Tier 1 — Signal Processing Pipeline

**Location:** `benchy/edge/rca/signal_processing.py`

Deterministic EE calculations. No LLM involved. Every metric gets computed and compared against a `ThresholdSpec` (expected values from datasheets or test configuration), producing a `PASS` / `WARN` / `FAIL` verdict.

### Voltage / Power Rail Analysis

| Metric | Formula / Method | Unit | What It Detects |
|--------|-----------------|------|-----------------|
| DC Level | `mean(samples)` | V | Voltage droop, regulator dropout, wrong setpoint |
| Ripple (Vpp) | `max - min` | mV | Decoupling issues, switching noise, load transients |
| RMS Voltage | `√(mean(samples²))` | V | True power delivery including AC component |
| Dominant Frequency | FFT → `argmax(magnitudes[1:])` | Hz | Switching regulator freq, oscillation, clock bleed |
| Rise Time (10%-90%) | First 10%→90% crossing, `Δt × 1e9` | ns | Capacitive loading, weak drive strength |
| Fall Time (90%-10%) | First 90%→10% crossing, `Δt × 1e9` | ns | Discharge path impedance |
| Overshoot | `(V_peak - V_90%) / V_range × 100` | % | Impedance mismatch, LC resonance, ringing |
| Undershoot | `(V_10% - V_min) / V_range × 100` | % | Ground bounce, inductive kickback |
| Settling Time | Time to stay within ±2% of final value | μs | Stability, damping factor |
| Slew Rate | `dV/dt` at steepest point | V/μs | Driver strength, bandwidth limitation |

### CAN Bus Analysis

| Metric | Formula | Unit | Expected (Healthy) | What It Detects |
|--------|---------|------|--------------------|-----------------|
| Dominant V_diff | `mean(CAN_H - CAN_L)` where `V_diff > 0.5V` | V | 1.5–3.0V | Transceiver power, termination |
| Recessive V_diff | `mean(CAN_H - CAN_L)` where `V_diff ≤ 0.5V` | V | < 0.5V | Bus idle level, termination |
| Common-Mode | `mean((CAN_H + CAN_L) / 2)` | V | 2.0–3.0V | Ground offset between nodes |
| Bit Rate | Zero-crossing interval → `1 / (2 × avg_half_bit)` | bps | Configured rate ±0.5% | Clock accuracy, bit timing |

### Power Supply Analysis

| Metric | Source | Unit | What It Detects |
|--------|--------|------|-----------------|
| Supply Voltage | PSU telemetry `V_out` | V | PSU setpoint error, cable drop |
| Load Current | PSU telemetry `I_out` | mA | Short circuit, excess peripheral draw |
| Power Consumption | `V × I` | mW | Power budget tracking |

### Threshold Spec

Every analysis takes a `ThresholdSpec` that defines expected values:

```python
ThresholdSpec(
    dc_voltage=3.3,          # nominal DC level (V)
    dc_tolerance_pct=5.0,    # ± percentage around nominal
    max_ripple_mv=100.0,     # max acceptable ripple peak-to-peak (mV)
    max_rise_time_ns=10000,  # max rise time (ns)
    max_overshoot_pct=10.0,  # max overshoot (%)
    max_settling_time_us=50, # max settling time (μs)
)
```

Verdicts are assigned as:
- **PASS**: value within spec
- **WARN**: value within 1.5× of spec limit (marginal)
- **FAIL**: value exceeds spec

---

## Tier 2 — Context-Aware Analyzer

**Location:** `benchy/edge/rca/context_analyzer.py`

Takes the structured metrics from Tier 1 and generates ranked hypotheses. Uses:

1. **Rule-based reasoning** — pattern matching on failed metrics to generate hypotheses with evidence chains and verification steps
2. **Board knowledge base** — ESP32-S3 datasheet specs, pin voltage levels, common failure modes, two-board fixture wiring
3. **Serial log analysis** — regex detection of brownout, guru meditation, watchdog, I2C timeout keywords
4. **Cross-metric correlation** — e.g., low voltage + high ripple together = stronger "regulator near current limit" signal
5. **LLM escalation prompt** — when confidence is low (< 40%), builds a structured prompt with all context for the Gemini agent to self-reason

### Hypothesis Structure

```python
Hypothesis(
    description="Excessive load current causing voltage droop on regulator output",
    confidence_pct=40,
    category="power",      # power | signal_integrity | protocol | firmware | hardware
    evidence=[
        "DC level 2.870V is 13.0% off nominal 3.3V",
        "ESP32-S3 WiFi TX can draw 310mA+, approaching AMS1117 limits",
    ],
    verification_steps=[
        "MEASURE: Read PSU current draw at current operating point",
        "PROBE: Connect scope CH2 to regulator input (VIN)",
        "FIRMWARE: Temporarily disable WiFi to reduce current draw",
    ],
)
```

### Hypothesis Categories

| Category | Meaning | Who Fixes It |
|----------|---------|--------------|
| `power` | Power delivery issue (regulator, decoupling, supply) | Hardware instruction or PSU adjustment |
| `signal_integrity` | Timing/reflection/ringing on signal lines | Hardware (termination, layout) |
| `protocol` | CAN/I2C/UART protocol-level error | Firmware config or hardware (pull-ups, termination) |
| `firmware` | Software bug causing hardware symptoms | Agent generates firmware fix |
| `hardware` | Physical board issue (solder, component, wiring) | User instructed to fix manually |

### Confidence Flow

1. Each per-metric hypothesis starts with a base confidence (10–50%)
2. Cross-metric correlations boost confidence (merged hypotheses get 1.2× multiplier)
3. Serial log matches add independent hypotheses at 40–50% confidence
4. All confidences are normalized so they sum to 100%
5. If top hypothesis ≥ 75% with ≥ 2 pieces of evidence → ready for root cause declaration

---

## Tier 3 — Gemini Chat Agent (Decision Maker)

**Location:** `benchy/frontend/src/app/api/agent/route.ts`

The Gemini agent in the chat UI IS the Tier 3 decision maker. It receives the RCA analysis as a tool result and decides what to do. This is intentional — the user converses with the same agent that makes diagnostic decisions.

### RCA Tools (to be wired into the agent)

```typescript
// Create an RCA session for a test
analyze_rca_start({
  test_goal: "Verify 3.3V rail stability under load",
  test_point: "U3 output pin 5",
}) → { session_id, session }

// Run analysis with current measurement data
analyze_rca({
  session_id: "abc123",
  waveform_data: [...],     // from capture_scope result
  sample_rate: 1000000,
  expected_voltage: 3.3,
  max_ripple_mv: 100,
  psu_voltage: 4.8,         // from PSU telemetry
  psu_current: 0.35,
  serial_log: "...",         // from serial monitor
}) → {
  session: { iteration: 1, status: "active" },
  overall_verdict: "FAIL",
  failed_metrics: [...],
  hypotheses: [
    { description: "...", confidence_pct: 45, evidence: [...], verification_steps: [...] },
    ...
  ],
  needs_llm_escalation: false,
}

// Generate final report
analyze_rca_report({
  session_id: "abc123",
  reason: "resolved",
}) → { report, report_markdown }
```

### Safety: User Confirmation Gate

**Critical rule:** The Gemini agent MUST wait for user confirmation before executing any action that energizes hardware or changes physical state. The flow is:

1. Gemini tells user what it wants to do: "I need to set the PSU to 5V on VIN and capture the 3.3V rail on scope CH1."
2. User confirms connections are correct and safe.
3. ONLY THEN does Gemini call `set_psu` / `capture_scope`.

This is enforced in the system prompt. The RCA pipeline's `verification_steps` are instructions for the user (e.g., "PROBE: Connect scope CH2 to regulator input") — Gemini must present these to the user and wait for acknowledgment before proceeding.

**PSU voltage note:** The DPS-150 PSU connects to the board's VIN pin (regulator input), NOT directly to the 3.3V rail. Setting PSU to 5V feeds the AMS1117 LDO which outputs 3.3V. The agent must never instruct the user to connect the PSU directly to a 3.3V rail at 5V — the board knowledge base explicitly documents the power architecture: `USB 5V input → AMS1117-3.3 LDO → 3.3V rail`.

### Decision Flow (Gemini's logic)

The Gemini agent uses the RCA results along with its own reasoning to decide:

1. **High confidence hypothesis (≥75%)** → Act on it
   - `category: "firmware"` → Generate firmware fix, compile, flash, re-test
   - `category: "hardware"` → Tell user what to fix physically
   - `category: "power"` → Adjust PSU settings or tell user about power issue

2. **Medium confidence (30-75%)** → Follow verification steps
   - The hypothesis includes specific `verification_steps` like:
     - `"PROBE: Connect scope CH2 to regulator input"` → Gemini asks user to probe
     - `"MEASURE: Read PSU current draw"` → Gemini calls PSU telemetry tool
     - `"FIRMWARE: Disable WiFi"` → Gemini generates test firmware

3. **Low confidence (<30%) or needs_llm_escalation** → The `escalation_context` field contains a pre-built prompt with all board knowledge + measurements that Gemini can use to reason more deeply

4. **After fix → Re-measure** → Run `analyze_rca` again to verify the fix worked

---

## Feedback Loop

```
    ┌──────────────────────────────────────────────┐
    │                                              │
    ▼                                              │
 [Measure]                                         │
    │ scope/capture, psu/state, serial/read         │
    ▼                                              │
 [Analyze] ← /rca/analyze                          │
    │ Tier 1: compute metrics                      │
    │ Tier 2: generate hypotheses                  │
    ▼                                              │
 [Decide] ← Gemini agent (Tier 3)                  │
    │                                              │
    ├── Fix firmware → compile/flash ──────────────┤
    ├── Instruct user → hardware fix ──────────────┤
    ├── Probe more → different test point ─────────┤
    ├── Adjust instrument → PSU/scope config ──────┤
    └── Declare root cause → generate report       │
                                                   │
    Max 5 iterations ──────────────────────────────┘
```

Each iteration:
1. Gemini calls measurement tools (scope, PSU, serial monitor)
2. Gemini calls `/rca/analyze` with the raw data
3. Gemini receives structured metrics + hypotheses
4. Gemini decides: fix, probe more, or declare root cause
5. If fix applied → re-measure → loop

---

## RCA Report Format

When root cause is declared or max iterations reached, a structured report is generated:

```
┌─────────────────────────────────────────────────┐
│ ROOT CAUSE ANALYSIS REPORT — Session abc123     │
├─────────────────────────────────────────────────┤
│                                                 │
│ OBSERVATION                                     │
│   Test Point: U3_output_3V3                     │
│   Expected:   3.30V ± 5% (3.135V – 3.465V)     │
│   Measured:   2.87V DC, 340mV ripple p-p        │
│   Verdict:    ❌ FAIL — 13% under nominal       │
│                                                 │
├─────────────────────────────────────────────────┤
│                                                 │
│ SIGNAL ANALYSIS                                 │
│   ❌ dc_voltage:    2.87V  (expected 3.14–3.47) │
│   ❌ ripple_voltage: 340mV (limit 100mV)        │
│   ❌ rise_time:      45μs  (limit 10μs)         │
│   ✅ overshoot:      2.3%  (limit 10%)          │
│   ⚠️  settling_time: 120μs (limit 50μs)         │
│   ℹ️  dominant_freq:  150kHz (switcher noise)    │
│                                                 │
├─────────────────────────────────────────────────┤
│                                                 │
│ HYPOTHESES (ranked by confidence)               │
│                                                 │
│   1. [50%] Combined low voltage + high ripple   │
│      indicates regulator near current limit     │
│      Category: power                            │
│      Evidence:                                  │
│      - DC 13% below nominal                    │
│      - Ripple 3.4× over limit                  │
│      - LDO output drops + ripple increases     │
│        together when approaching current limit  │
│      Verification:                              │
│      - MEASURE: Check total current draw        │
│      - FIRMWARE: Disable WiFi and re-test       │
│                                                 │
│   2. [16%] Brownout detector triggered          │
│      Category: power                            │
│      Evidence:                                  │
│      - Serial log contains brownout message     │
│                                                 │
│   3. [12%] Insufficient VIN to LDO regulator    │
│      Category: power                            │
│      Evidence:                                  │
│      - AMS1117 needs VIN ≥ 4.4V for 3.3V out   │
│                                                 │
├─────────────────────────────────────────────────┤
│                                                 │
│ ROOT CAUSE (if declared)                        │
│   Excessive load current causing regulator to   │
│   operate near its current limit, resulting in  │
│   voltage droop and increased ripple.           │
│   Confidence: 50%                               │
│   Category: power                               │
│                                                 │
├─────────────────────────────────────────────────┤
│                                                 │
│ RECOMMENDED ACTIONS                             │
│   1. [INSTRUMENT] Read PSU current draw         │
│   2. [FIRMWARE] Disable WiFi and re-test        │
│   3. [HARDWARE] Consider higher-current LDO     │
│                                                 │
├─────────────────────────────────────────────────┤
│                                                 │
│ DECISION TREE (for next steps)                  │
│                                                 │
│   IF VIN < 4.5V                                 │
│     → Problem is upstream (check USB/PSU)       │
│   IF VIN ≥ 4.5V AND I_load > 500mA             │
│     → Excess current (check for shorts)         │
│   IF VIN ≥ 4.5V AND I_load ≤ 500mA             │
│     → Regulator damaged (replace U3)            │
│                                                 │
├─────────────────────────────────────────────────┤
│                                                 │
│ ITERATION LOG                                   │
│   Iteration 1: Measured 3V3 rail → FAIL         │
│     Top: "regulator near current limit" (50%)   │
│   Iteration 2: Added PSU telemetry + serial log │
│     Top: "brownout confirmed" (65%)             │
│   Iteration 3: Disabled WiFi, re-measured       │
│     Top: "load current was the cause" (85%)     │
│                                                 │
└─────────────────────────────────────────────────┘
```

---

## File Structure

```
benchy/edge/rca/
├── __init__.py              # Module exports
├── signal_processing.py     # Tier 1 — EE calculations, metrics, verdicts
├── context_analyzer.py      # Tier 2 — Hypothesis generation, board knowledge
├── orchestrator.py          # Pipeline (Tier 1+2) + session management
├── report.py                # RCA report generation (dict + markdown)
├── rca_endpoints.py         # FastAPI router for /rca/* endpoints
└── simulated_test.py        # Verification suite with synthetic data
```

---

## Integration Steps

### 1. Mount RCA endpoints on the edge worker

In `benchy/edge/worker.py`:

```python
from rca.rca_endpoints import rca_router
app.include_router(rca_router, prefix="/rca")
```

### 2. Add RCA tools to the Gemini agent

In `benchy/frontend/src/app/api/agent/route.ts`, add three tools:

```typescript
analyze_rca_start: tool({
  description: "Start a new Root Cause Analysis session for diagnosing a hardware issue.",
  inputSchema: z.object({
    test_goal: z.string().describe("What is being tested"),
    test_point: z.string().describe("Physical test point name"),
  }),
  execute: async ({ test_goal, test_point }) => {
    return await runnerCall("/rca/session", { test_goal, test_point });
  },
}),

analyze_rca: tool({
  description: `Run RCA analysis on measurement data. Feed in scope waveforms, PSU telemetry,
and/or serial logs. Returns structured metrics with PASS/WARN/FAIL verdicts and ranked
hypotheses with evidence chains and verification steps.
Use this AFTER capturing scope/PSU/serial data to diagnose failures.`,
  inputSchema: z.object({
    session_id: z.string(),
    waveform_data: z.array(z.number()).optional(),
    sample_rate: z.number().default(1000000),
    expected_voltage: z.number().optional(),
    max_ripple_mv: z.number().optional(),
    psu_voltage: z.number().optional(),
    psu_current: z.number().optional(),
    serial_log: z.string().optional(),
  }),
  execute: async (args) => {
    return await runnerCall("/rca/analyze", args);
  },
}),

analyze_rca_report: tool({
  description: "Generate the final RCA report for a diagnosis session.",
  inputSchema: z.object({
    session_id: z.string(),
    reason: z.string().default("resolved"),
  }),
  execute: async (args) => {
    return await runnerCall("/rca/report", args);
  },
}),
```

### 3. Update Gemini system prompt

Add to the system prompt in `route.ts`:

```
When diagnosing hardware failures, use the RCA analysis pipeline:
1. Capture measurement data (scope, PSU, serial)
2. Call analyze_rca_start to create a session
3. Call analyze_rca with measurement data — you'll get structured metrics and ranked hypotheses
4. Review the hypotheses and their verification steps
5. Either: fix firmware, instruct user on hardware fix, or probe more test points
6. After each fix or new measurement, call analyze_rca again to update the analysis
7. When confident in root cause, call analyze_rca_report to generate the final report

The RCA tool gives you EE analysis you can't do yourself (FFT, rise time, threshold comparisons).
Use it instead of guessing from raw waveform numbers.

SAFETY — USER CONFIRMATION GATE:
Before ANY action that energizes hardware or changes physical state, you MUST:
1. Tell the user exactly what you're about to do and what should be connected
2. Wait for the user to confirm the setup is correct
3. Only then execute the instrument commands
NEVER set PSU voltage or enable output without user confirmation.
NEVER instruct the user to connect the PSU directly to a 3.3V rail — the PSU feeds
the board VIN (regulator input). The LDO converts to 3.3V.
If the RCA analysis suggests probing a different test point, tell the user to move the
probe and confirm before capturing.
```

---

## Simulated Verification

The `simulated_test.py` module validates the entire pipeline with 6 scenarios:

| # | Scenario | Simulated Data | Expected Result |
|---|----------|----------------|-----------------|
| 1 | Droopy 3.3V Rail | 2.87V DC, 340mV ripple, brownout log | FAIL, regulator/load hypotheses |
| 2 | Healthy 3.3V Rail | 3.3V ± noise | PASS, no hypotheses |
| 3 | Healthy CAN Bus | Correct CAN_H/CAN_L levels | PASS |
| 4 | CAN Bad Termination | Excessive differential + ringing | FAIL, termination hypothesis |
| 5 | I2C Timeout (Log Only) | Serial log with NACK errors | I2C hypothesis from log |
| 6 | Multi-Iteration Loop | 3 iterations → auto-report | Session tracking + report generation |

Run: `cd benchy/edge && python3 -m rca.simulated_test`

All 6/6 pass.

---

## EE Equations Reference

For context on the signal processing calculations:

**Rise Time & Bandwidth:**
- `t_r = 0.35 / BW` (single-pole approximation)
- Measured as 10%→90% of signal swing

**Overshoot (damped oscillation):**
- `OS% = (V_peak - V_final) / V_final × 100`
- Related to damping ratio: `OS% = e^(-πζ/√(1-ζ²)) × 100`

**RC Time Constant (I2C pull-up sizing):**
- `t_r ≈ 0.8473 × R_pullup × C_bus`
- I2C spec: t_r < 1μs for standard mode, < 300ns for fast mode

**CAN Bus Levels (ISO 11898):**
- Dominant: CAN_H = 3.5V, CAN_L = 1.5V → V_diff = 2.0V
- Recessive: CAN_H = CAN_L = 2.5V → V_diff = 0V
- Bus must be terminated with 120Ω at each end

**Power Dissipation:**
- `P = V × I` (PSU telemetry gives both)
- LDO dissipation: `P_ldo = (V_in - V_out) × I_out`
- AMS1117-3.3 at 5V in, 350mA: `P = (5 - 3.3) × 0.35 = 0.595W`

**Voltage Regulation:**
- Load regulation: `ΔV_out / ΔI_load` (should be < 1% for good LDO)
- Line regulation: `ΔV_out / ΔV_in` (should be < 0.2%)
- Dropout: `V_in_min = V_out + V_dropout` (AMS1117: 1.1V typical)

**FFT for Noise Source Identification:**
- Switching regulator: dominant frequency = switching frequency (typically 100kHz–2MHz)
- 50/60Hz: mains pickup through ground loop
- Clock harmonics: multiples of crystal frequency (40MHz for ESP32)

---

## Future Extensions

- **Waveform image analysis**: Send scope chart PNGs to Gemini vision for visual pattern recognition alongside numerical analysis
- **Firmware-aware analysis**: Parse the DUT firmware source to correlate peripheral initialization with observed symptoms
- **Historical comparison**: Compare current measurements against known-good baselines from previous test runs
- **Automated probe routing**: If the setup has a multiplexer/relay matrix, auto-switch probe points without user intervention
- **Confidence accumulation**: Across iterations, hypotheses that keep getting evidence should ramp faster; ones that lose evidence should decay
