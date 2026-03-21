"""
Tier 2 — Context-Aware Subagent

Takes structured metrics from Tier 1 and reasons about them using
board-specific knowledge (datasheets, schematics, pin maps).

Produces ranked hypotheses with evidence chains.
Does NOT decide actions — that's Tier 3's job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .signal_processing import SignalAnalysis, Verdict, MetricResult


# ---------------------------------------------------------------------------
# Board knowledge base — structured context for the subagent
# ---------------------------------------------------------------------------

# ESP32-S3 DevKitC-1 board knowledge
ESP32_S3_BOARD_CONTEXT = """
## ESP32-S3-DevKitC-1 Board Reference

### Power Architecture
- USB 5V input → AMS1117-3.3 LDO → 3.3V rail
- AMS1117 dropout: 1.1V typical (needs VIN ≥ 4.4V for 3.3V out)
- AMS1117 max output current: 800mA
- ESP32-S3 typical current: 80mA idle, 310mA WiFi TX, 355mA WiFi+BT
- Brownout detector threshold: configurable, default 2.43V

### Pin Voltage Specifications
- GPIO output HIGH: 3.0V–3.3V (CMOS logic)
- GPIO output LOW: 0V–0.1V
- GPIO input HIGH threshold: 0.75 × VDD = 2.475V
- GPIO input LOW threshold: 0.25 × VDD = 0.825V
- ADC reference: 0–3.1V (with 11dB attenuation)
- Absolute max on any pin: -0.3V to VDD+0.3V = 3.6V

### CAN/TWAI Peripheral
- ESP32-S3 has built-in TWAI controller (CAN 2.0B compatible)
- Requires external transceiver (SN65HVD230 or similar)
- TX/RX are 3.3V logic level to transceiver
- Bus termination: 120Ω at each end
- Supported rates: 25kbps–1Mbps

### I2C Specifications
- Default: 100kHz (standard mode), supports up to 400kHz (fast mode)
- Requires external pull-ups (4.7kΩ typical for 100kHz)
- SDA/SCL on GPIO 8/9 in this wiring

### UART Specifications
- Default baud: 115200
- Logic levels: 3.3V (no RS-232 levels)
- TX on GPIO 17, fixture RX on GPIO 18

### Common Failure Modes
- Brownout resets during WiFi TX (current spike > LDO capacity)
- I2C hang when slave clock-stretches beyond master timeout
- CAN bus errors with missing/wrong termination resistance
- GPIO damage from overvoltage (>3.6V absolute max)
- Boot loop from GPIO 0/46 strapping pin conflicts

### SAFETY — Power Architecture
- PSU connects to VIN (regulator input), NOT directly to the 3.3V rail
- PSU at 5V → AMS1117 LDO → 3.3V output. This is the CORRECT configuration.
- NEVER connect PSU directly to 3.3V rail at 5V — this will damage the board
- ALWAYS confirm physical connections with user before energizing PSU
- Max safe VIN: 15V (AMS1117 abs max), typical: 5V
"""

# Two-board test fixture wiring
FIXTURE_WIRING_CONTEXT = """
## Two-Board Test Fixture Wiring

### DUT (Device Under Test) — ESP32-S3 Board A
### Fixture (Test Partner) — ESP32-S3 Board B

| DUT Pin    | Fixture Pin | Signal      | Notes                    |
|------------|-------------|-------------|--------------------------|
| GPIO 8     | GPIO 8      | I2C SDA     | Shared bus, need pullups |
| GPIO 9     | GPIO 9      | I2C SCL     | Shared bus, need pullups |
| GPIO 17    | GPIO 18     | UART TX→RX  | DUT transmits to fixture |
| GPIO 5     | GPIO 6      | CAN TX→RX   | Through transceiver      |
| GPIO 6     | GPIO 5      | CAN RX→TX   | Through transceiver      |
| EN         | GPIO 7      | Reset ctrl  | Fixture can reset DUT    |
| VIN        | GPIO 4      | Load inject | MOSFET for droop sim     |

### Instruments
- Analog Discovery 2: CH1/CH2 can probe any of the above signals
- DPS-150 PSU: Powers DUT VIN rail (0–30V, 0–5.5A, programmable)
"""


# ---------------------------------------------------------------------------
# Hypothesis data structure
# ---------------------------------------------------------------------------

@dataclass
class Hypothesis:
    description: str
    confidence_pct: float  # 0–100
    evidence: list[str] = field(default_factory=list)
    category: str = ""  # "power", "signal_integrity", "protocol", "firmware", "hardware"
    verification_steps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "confidence_pct": self.confidence_pct,
            "evidence": self.evidence,
            "category": self.category,
            "verification_steps": self.verification_steps,
        }


# ---------------------------------------------------------------------------
# Context Analyzer — Tier 2 engine
# ---------------------------------------------------------------------------

class ContextAnalyzer:
    """
    Generates ranked hypotheses based on signal analysis results and
    board-specific knowledge. Uses rule-based reasoning for deterministic
    scenarios and prepares structured prompts for LLM escalation.
    """

    @staticmethod
    def analyze(
        signal_analyses: list[SignalAnalysis],
        serial_log: Optional[str] = None,
        firmware_source: Optional[str] = None,
    ) -> list[Hypothesis]:
        """
        Generate hypotheses from one or more signal analyses.
        Returns hypotheses sorted by confidence (highest first).
        """
        hypotheses: list[Hypothesis] = []

        for analysis in signal_analyses:
            failed = analysis.failed_metrics()
            warned = analysis.warned_metrics()

            if not failed and not warned:
                continue

            # Route to specialized hypothesis generators
            for metric in failed + warned:
                new_hyps = ContextAnalyzer._hypothesize_metric(metric, analysis)
                hypotheses.extend(new_hyps)

            # Cross-metric correlations
            cross_hyps = ContextAnalyzer._cross_correlate(analysis)
            hypotheses.extend(cross_hyps)

        # Check serial log for clues
        if serial_log:
            log_hyps = ContextAnalyzer._analyze_serial_log(serial_log)
            hypotheses.extend(log_hyps)

        # Deduplicate and merge similar hypotheses
        hypotheses = ContextAnalyzer._merge_similar(hypotheses)

        # Sort by confidence descending
        hypotheses.sort(key=lambda h: h.confidence_pct, reverse=True)

        # Normalize confidences so they sum to ~100 for top hypotheses
        total = sum(h.confidence_pct for h in hypotheses)
        if total > 0 and total != 100:
            for h in hypotheses:
                h.confidence_pct = round(h.confidence_pct / total * 100, 1)

        return hypotheses

    # ----- Per-metric hypothesis generation --------------------------------

    @staticmethod
    def _hypothesize_metric(metric: MetricResult, analysis: SignalAnalysis) -> list[Hypothesis]:
        hyps: list[Hypothesis] = []

        if metric.name == "dc_voltage":
            hyps.extend(ContextAnalyzer._hyp_dc_voltage(metric, analysis))
        elif metric.name == "ripple_voltage":
            hyps.extend(ContextAnalyzer._hyp_ripple(metric, analysis))
        elif metric.name == "rise_time":
            hyps.extend(ContextAnalyzer._hyp_rise_time(metric, analysis))
        elif metric.name == "overshoot":
            hyps.extend(ContextAnalyzer._hyp_overshoot(metric, analysis))
        elif metric.name in ("can_dominant_differential", "can_recessive_differential"):
            hyps.extend(ContextAnalyzer._hyp_can_levels(metric, analysis))
        elif metric.name == "can_common_mode":
            hyps.extend(ContextAnalyzer._hyp_can_common_mode(metric, analysis))
        elif metric.name == "load_current":
            hyps.extend(ContextAnalyzer._hyp_overcurrent(metric, analysis))
        elif metric.name == "supply_voltage":
            hyps.extend(ContextAnalyzer._hyp_supply_voltage(metric, analysis))

        return hyps

    # ----- DC voltage hypotheses -------------------------------------------

    @staticmethod
    def _hyp_dc_voltage(metric: MetricResult, analysis: SignalAnalysis) -> list[Hypothesis]:
        hyps = []
        is_low = metric.value < (metric.expected_min or 0)
        is_high = metric.value > (metric.expected_max or float("inf"))

        if is_low:
            hyps.append(Hypothesis(
                description="Excessive load current causing voltage droop on regulator output",
                confidence_pct=40,
                evidence=[
                    metric.detail,
                    "Voltage below nominal suggests regulator is drooping under load",
                    "ESP32-S3 WiFi TX can draw 310mA+, approaching AMS1117 limits with other peripherals",
                ],
                category="power",
                verification_steps=[
                    "MEASURE: Read PSU current draw at current operating point",
                    "PROBE: Connect scope CH2 to regulator input (VIN) to check upstream voltage",
                    "FIRMWARE: Temporarily disable WiFi to reduce current draw and re-measure",
                ],
            ))
            hyps.append(Hypothesis(
                description="Insufficient input voltage to LDO regulator (dropout condition)",
                confidence_pct=25,
                evidence=[
                    metric.detail,
                    "AMS1117 dropout is 1.1V — needs VIN ≥ 4.4V for 3.3V output",
                    "If USB power is sagging or PSU set too low, regulator enters dropout",
                ],
                category="power",
                verification_steps=[
                    "PROBE: Measure VIN at regulator input pin",
                    "INSTRUMENT: Check PSU set voltage vs actual output under load",
                ],
            ))
            hyps.append(Hypothesis(
                description="Faulty or degraded voltage regulator",
                confidence_pct=10,
                evidence=[
                    metric.detail,
                    "If VIN is adequate and load is within spec, regulator itself may be damaged",
                ],
                category="hardware",
                verification_steps=[
                    "MEASURE: Check regulator case temperature (overheating indicates failure)",
                    "HARDWARE: Replace regulator if other causes ruled out",
                ],
            ))

        if is_high:
            hyps.append(Hypothesis(
                description="Regulator output over-voltage — possible feedback resistor issue or wrong part",
                confidence_pct=35,
                evidence=[
                    metric.detail,
                    "Output above nominal is unusual for LDO; check if correct part is installed",
                ],
                category="hardware",
                verification_steps=[
                    "HARDWARE: Verify regulator part number matches schematic (AMS1117-3.3)",
                    "PROBE: Check feedback/adjust pin voltage",
                ],
            ))

        return hyps

    # ----- Ripple hypotheses -----------------------------------------------

    @staticmethod
    def _hyp_ripple(metric: MetricResult, analysis: SignalAnalysis) -> list[Hypothesis]:
        hyps = []
        # Check if dominant frequency was captured
        dom_freq = analysis.raw_stats.get("dominant_freq_hz")

        hyps.append(Hypothesis(
            description="Insufficient decoupling capacitance near load",
            confidence_pct=35,
            evidence=[
                metric.detail,
                f"Ripple frequency: {dom_freq/1000:.0f}kHz" if dom_freq else "Ripple frequency not yet determined",
                "High-frequency ripple often caused by inadequate bypass caps close to IC power pins",
            ],
            category="power",
            verification_steps=[
                "HARDWARE: Verify 100nF ceramic cap is placed close to ESP32 VDD pins",
                "HARDWARE: Add additional 10μF bulk cap if missing",
            ],
        ))

        if dom_freq and dom_freq > 50_000:  # > 50kHz suggests switching noise
            hyps.append(Hypothesis(
                description="Switching regulator noise coupling into 3.3V rail",
                confidence_pct=25,
                evidence=[
                    metric.detail,
                    f"Dominant frequency {dom_freq/1000:.0f}kHz is in switching regulator range",
                    "If board has a buck converter upstream, its switching noise may couple through",
                ],
                category="power",
                verification_steps=[
                    "PROBE: Measure upstream switching regulator output for same frequency",
                    "HARDWARE: Add ferrite bead between switching output and LDO input",
                ],
            ))

        hyps.append(Hypothesis(
            description="ESR of output capacitor too high",
            confidence_pct=15,
            evidence=[
                metric.detail,
                "Electrolytic caps degrade over time, increasing ESR and ripple",
            ],
            category="hardware",
            verification_steps=[
                "HARDWARE: Replace output cap with known-good low-ESR ceramic or tantalum",
            ],
        ))

        return hyps

    # ----- Rise time hypotheses --------------------------------------------

    @staticmethod
    def _hyp_rise_time(metric: MetricResult, analysis: SignalAnalysis) -> list[Hypothesis]:
        hyps = []
        hyps.append(Hypothesis(
            description="Excessive capacitive loading on signal line",
            confidence_pct=40,
            evidence=[
                metric.detail,
                "Slow rise time typically indicates too much capacitance on the line",
                "Long traces, multiple fanout, or scope probe capacitance can cause this",
            ],
            category="signal_integrity",
            verification_steps=[
                "HARDWARE: Check trace length and fanout on this signal",
                "INSTRUMENT: Use 10× probe to reduce scope loading (10pF vs 100pF)",
            ],
        ))
        hyps.append(Hypothesis(
            description="Weak drive strength or missing/wrong pull-up resistor",
            confidence_pct=30,
            evidence=[
                metric.detail,
                "If GPIO drive strength is set to minimum, rise time increases",
                "For open-drain signals (I2C), pull-up value determines rise time: t_r ≈ 0.8473 × R × C",
            ],
            category="firmware",
            verification_steps=[
                "FIRMWARE: Increase GPIO drive strength if available",
                "HARDWARE: For I2C, try 2.2kΩ pull-ups instead of 4.7kΩ",
            ],
        ))
        return hyps

    # ----- Overshoot hypotheses --------------------------------------------

    @staticmethod
    def _hyp_overshoot(metric: MetricResult, analysis: SignalAnalysis) -> list[Hypothesis]:
        hyps = []
        hyps.append(Hypothesis(
            description="Impedance mismatch causing signal reflection",
            confidence_pct=35,
            evidence=[
                metric.detail,
                "Overshoot/ringing typically caused by impedance discontinuities in the signal path",
                "Especially problematic on fast edges (< 5ns rise time)",
            ],
            category="signal_integrity",
            verification_steps=[
                "HARDWARE: Add series termination resistor (22–33Ω) near driver output",
                "PROBE: Measure at driver output vs receiver input to localize reflection",
            ],
        ))
        hyps.append(Hypothesis(
            description="Inductance in power/ground return path",
            confidence_pct=25,
            evidence=[
                metric.detail,
                "Long ground wires or vias add inductance, causing ringing on fast transients",
            ],
            category="hardware",
            verification_steps=[
                "HARDWARE: Shorten ground connection, use ground plane if possible",
                "HARDWARE: Add decoupling cap at signal destination",
            ],
        ))
        return hyps

    # ----- CAN level hypotheses --------------------------------------------

    @staticmethod
    def _hyp_can_levels(metric: MetricResult, analysis: SignalAnalysis) -> list[Hypothesis]:
        hyps = []
        if metric.name == "can_dominant_differential" and metric.verdict != Verdict.PASS:
            if metric.value < (metric.expected_min or 0):
                hyps.append(Hypothesis(
                    description="CAN bus termination resistance too low or missing transceiver power",
                    confidence_pct=40,
                    evidence=[
                        metric.detail,
                        "Low dominant differential suggests transceiver not driving properly",
                        "Check transceiver VCC and 120Ω termination at both ends",
                    ],
                    category="hardware",
                    verification_steps=[
                        "HARDWARE: Verify 120Ω termination resistors at both bus ends",
                        "PROBE: Measure transceiver VCC pin — should be 3.3V",
                        "HARDWARE: Check solder joints on transceiver IC",
                    ],
                ))
            elif metric.value > (metric.expected_max or float("inf")):
                hyps.append(Hypothesis(
                    description="Missing bus termination causing reflections on CAN bus",
                    confidence_pct=45,
                    evidence=[
                        metric.detail,
                        "High dominant voltage with ringing suggests unterminated bus",
                        "CAN bus requires 120Ω termination at each end",
                    ],
                    category="hardware",
                    verification_steps=[
                        "HARDWARE: Add 120Ω termination resistor between CAN_H and CAN_L at both ends",
                        "PROBE: Re-capture after adding termination to verify",
                    ],
                ))
        return hyps

    # ----- CAN common-mode hypotheses --------------------------------------

    @staticmethod
    def _hyp_can_common_mode(metric: MetricResult, analysis: SignalAnalysis) -> list[Hypothesis]:
        hyps = []
        if metric.verdict != Verdict.PASS:
            hyps.append(Hypothesis(
                description="Ground offset between CAN nodes causing common-mode shift",
                confidence_pct=35,
                evidence=[
                    metric.detail,
                    "Common-mode voltage outside 2.0–3.0V suggests ground potential difference",
                    "Can be caused by different power supplies or long ground wires",
                ],
                category="hardware",
                verification_steps=[
                    "HARDWARE: Verify both boards share a common ground reference",
                    "PROBE: Measure ground potential difference between DUT and fixture boards",
                ],
            ))
        return hyps

    # ----- Overcurrent hypotheses ------------------------------------------

    @staticmethod
    def _hyp_overcurrent(metric: MetricResult, analysis: SignalAnalysis) -> list[Hypothesis]:
        hyps = []
        hyps.append(Hypothesis(
            description="Short circuit or unintended current path on board",
            confidence_pct=30,
            evidence=[
                metric.detail,
                "Current exceeding expected maximum suggests a short or unintended load",
            ],
            category="hardware",
            verification_steps=[
                "HARDWARE: Inspect board for solder bridges, especially near power pins",
                "FIRMWARE: Disable all peripherals and re-measure to isolate the draw",
                "PROBE: Use thermal camera or finger test to find hot components",
            ],
        ))
        hyps.append(Hypothesis(
            description="Firmware activating too many peripherals simultaneously",
            confidence_pct=30,
            evidence=[
                metric.detail,
                "WiFi + BT + peripherals can exceed 400mA on ESP32-S3",
            ],
            category="firmware",
            verification_steps=[
                "FIRMWARE: Audit active peripherals — disable unused ones",
                "FIRMWARE: Stagger peripheral initialization to avoid current spikes",
            ],
        ))
        return hyps

    # ----- Supply voltage hypotheses ---------------------------------------

    @staticmethod
    def _hyp_supply_voltage(metric: MetricResult, analysis: SignalAnalysis) -> list[Hypothesis]:
        hyps = []
        if metric.value < (metric.expected_min or 0):
            hyps.append(Hypothesis(
                description="PSU voltage set too low or cable voltage drop",
                confidence_pct=40,
                evidence=[
                    metric.detail,
                    "Check PSU setpoint and measure at board terminals (not PSU output)",
                    "Long or thin USB cables can drop 0.2–0.5V under load",
                ],
                category="hardware",
                verification_steps=[
                    "INSTRUMENT: Verify PSU setpoint matches intended voltage",
                    "PROBE: Measure voltage at board VIN pin directly",
                    "HARDWARE: Use shorter/thicker USB cable or power directly",
                ],
            ))
        return hyps

    # ----- Serial log analysis ---------------------------------------------

    @staticmethod
    def _analyze_serial_log(log: str) -> list[Hypothesis]:
        hyps = []
        log_lower = log.lower()

        if "brownout" in log_lower or "brown out" in log_lower:
            hyps.append(Hypothesis(
                description="Brownout detector triggered — supply voltage dipped below threshold",
                confidence_pct=50,
                evidence=[
                    "Serial log contains brownout reset message",
                    "ESP32-S3 brownout threshold default is 2.43V",
                    "Typically caused by current spike during WiFi TX or peripheral init",
                ],
                category="power",
                verification_steps=[
                    "PROBE: Capture power rail during boot sequence to see voltage dip",
                    "INSTRUMENT: Increase PSU current limit",
                    "FIRMWARE: Raise brownout threshold or add delay before WiFi init",
                ],
            ))

        if "guru meditation" in log_lower or "panic" in log_lower:
            hyps.append(Hypothesis(
                description="CPU exception (Guru Meditation) — firmware crash",
                confidence_pct=45,
                evidence=[
                    "Serial log contains panic/guru meditation error",
                    "Could be null pointer, stack overflow, or watchdog timeout",
                ],
                category="firmware",
                verification_steps=[
                    "FIRMWARE: Decode backtrace using addr2line or ESP-IDF monitor",
                    "FIRMWARE: Check for stack overflow — increase task stack size",
                    "FIRMWARE: Review interrupt handlers for race conditions",
                ],
            ))

        if "wdt" in log_lower or "watchdog" in log_lower:
            hyps.append(Hypothesis(
                description="Watchdog timer reset — task blocked too long",
                confidence_pct=40,
                evidence=[
                    "Serial log indicates watchdog trigger",
                    "Task watchdog fires if a task doesn't yield within timeout (default 5s)",
                ],
                category="firmware",
                verification_steps=[
                    "FIRMWARE: Add vTaskDelay() or yield points in long-running loops",
                    "FIRMWARE: Increase watchdog timeout if operation legitimately takes long",
                ],
            ))

        if "i2c" in log_lower and ("timeout" in log_lower or "nak" in log_lower or "nack" in log_lower):
            hyps.append(Hypothesis(
                description="I2C communication failure — slave not responding",
                confidence_pct=40,
                evidence=[
                    "Serial log shows I2C timeout or NACK",
                    "Slave device may be unpowered, wrong address, or bus stuck",
                ],
                category="protocol",
                verification_steps=[
                    "PROBE: Capture I2C SDA/SCL on scope to verify bus activity",
                    "FIRMWARE: Run I2C scanner to detect devices on bus",
                    "HARDWARE: Verify pull-up resistors on SDA/SCL (4.7kΩ to 3.3V)",
                ],
            ))

        return hyps

    # ----- Cross-correlation between metrics -------------------------------

    @staticmethod
    def _cross_correlate(analysis: SignalAnalysis) -> list[Hypothesis]:
        hyps = []
        metrics_by_name = {m.name: m for m in analysis.metrics}

        # Low voltage + high ripple → likely a load/decoupling issue
        dc = metrics_by_name.get("dc_voltage")
        ripple = metrics_by_name.get("ripple_voltage")
        if dc and ripple and dc.verdict == Verdict.FAIL and ripple.verdict == Verdict.FAIL:
            hyps.append(Hypothesis(
                description="Combined low voltage + high ripple indicates regulator near current limit",
                confidence_pct=50,
                evidence=[
                    dc.detail,
                    ripple.detail,
                    "When an LDO approaches current limit, output voltage drops and ripple increases",
                    "This is a strong indicator of excessive load current",
                ],
                category="power",
                verification_steps=[
                    "MEASURE: Check total current draw immediately",
                    "FIRMWARE: Disable WiFi/BT and re-test to confirm load is the cause",
                    "HARDWARE: Consider higher-current regulator if load is legitimate",
                ],
            ))

        # Slow rise time + overshoot → impedance mismatch with capacitive load
        rise = metrics_by_name.get("rise_time")
        overshoot = metrics_by_name.get("overshoot")
        if (rise and overshoot
                and rise.verdict == Verdict.FAIL
                and overshoot.verdict == Verdict.FAIL):
            hyps.append(Hypothesis(
                description="Slow rise time combined with overshoot suggests LC resonance in signal path",
                confidence_pct=40,
                evidence=[
                    rise.detail,
                    overshoot.detail,
                    "Parasitic inductance + capacitance can form resonant circuit causing both effects",
                ],
                category="signal_integrity",
                verification_steps=[
                    "HARDWARE: Add RC snubber or series damping resistor",
                    "PROBE: Capture at multiple points along trace to find resonance location",
                ],
            ))

        return hyps

    # ----- Merge similar hypotheses ----------------------------------------

    @staticmethod
    def _merge_similar(hypotheses: list[Hypothesis]) -> list[Hypothesis]:
        """Merge hypotheses with very similar descriptions."""
        if len(hypotheses) <= 1:
            return hypotheses

        merged: list[Hypothesis] = []
        used = set()

        for i, h1 in enumerate(hypotheses):
            if i in used:
                continue
            for j, h2 in enumerate(hypotheses[i + 1:], start=i + 1):
                if j in used:
                    continue
                # Simple similarity: same category and >50% word overlap
                words1 = set(h1.description.lower().split())
                words2 = set(h2.description.lower().split())
                overlap = len(words1 & words2) / max(len(words1 | words2), 1)
                if overlap > 0.5 and h1.category == h2.category:
                    # Merge: keep higher confidence, combine evidence
                    h1.confidence_pct = max(h1.confidence_pct, h2.confidence_pct) * 1.2
                    h1.evidence = list(dict.fromkeys(h1.evidence + h2.evidence))
                    h1.verification_steps = list(dict.fromkeys(
                        h1.verification_steps + h2.verification_steps
                    ))
                    used.add(j)
            merged.append(h1)

        return merged

    # ----- Build LLM prompt for complex cases ------------------------------

    @staticmethod
    def build_llm_prompt(
        signal_analyses: list[SignalAnalysis],
        hypotheses: list[Hypothesis],
        serial_log: Optional[str] = None,
    ) -> str:
        """
        Build a structured prompt for LLM escalation when rule-based
        analysis isn't confident enough (top hypothesis < 40%).
        """
        prompt_parts = [
            "You are an expert electrical engineer diagnosing a hardware test failure.",
            "Analyze the following measurements and generate a root cause diagnosis.",
            "",
            "## Board Context",
            ESP32_S3_BOARD_CONTEXT,
            "",
            "## Fixture Wiring",
            FIXTURE_WIRING_CONTEXT,
            "",
            "## Measurements",
        ]

        for analysis in signal_analyses:
            prompt_parts.append(f"\n### Test Point: {analysis.test_point}")
            prompt_parts.append(f"Overall Verdict: {analysis.overall_verdict.value}")
            for m in analysis.metrics:
                icon = "✅" if m.verdict == Verdict.PASS else "⚠️" if m.verdict == Verdict.WARN else "❌"
                prompt_parts.append(f"  {icon} {m.name}: {m.value} {m.unit} — {m.detail}")

        if serial_log:
            prompt_parts.append("\n## Serial Log (last 50 lines)")
            lines = serial_log.strip().split("\n")
            prompt_parts.append("\n".join(lines[-50:]))

        if hypotheses:
            prompt_parts.append("\n## Preliminary Hypotheses (from rule engine)")
            for i, h in enumerate(hypotheses[:5], 1):
                prompt_parts.append(f"{i}. [{h.confidence_pct:.0f}%] {h.description}")
                for e in h.evidence:
                    prompt_parts.append(f"   - {e}")

        prompt_parts.append("""
## Your Task
1. Evaluate the preliminary hypotheses — adjust confidence or add new ones.
2. Identify the most likely root cause with supporting evidence.
3. Recommend specific next actions (categorized as FIRMWARE, HARDWARE, INSTRUMENT, or PROBE).
4. If data is insufficient, specify exactly what additional measurement is needed.

Respond in this JSON format:
{
  "root_cause": "description of most likely root cause",
  "confidence_pct": 85,
  "evidence_chain": ["evidence 1", "evidence 2"],
  "hypotheses": [
    {"description": "...", "confidence_pct": 40, "category": "power"},
    ...
  ],
  "next_actions": [
    {"type": "FIRMWARE|HARDWARE|INSTRUMENT|PROBE", "description": "...", "priority": 1}
  ],
  "needs_more_data": false,
  "additional_measurements_needed": []
}""")

        return "\n".join(prompt_parts)
