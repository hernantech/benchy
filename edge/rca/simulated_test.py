"""
Simulated RCA verification — runs the full Tier 1 + Tier 2 pipeline against
synthetic oscilloscope/PSU data to validate the analysis and report generation.

Run directly:  python -m rca.simulated_test
"""

from __future__ import annotations

import json
import sys
import numpy as np

from .signal_processing import SignalProcessor, ThresholdSpec
from .context_analyzer import ContextAnalyzer
from .orchestrator import RCAPipeline
from .report import RCAReportGenerator


# ---------------------------------------------------------------------------
# Simulated waveform generators
# ---------------------------------------------------------------------------

def sim_droopy_3v3_rail(
    sample_rate: float = 1_000_000,
    duration_s: float = 0.01,
    dc_level: float = 2.87,
    ripple_freq: float = 150_000,
    ripple_amplitude: float = 0.17,
    noise_std: float = 0.02,
) -> np.ndarray:
    """
    Simulate a 3.3V rail that has drooped to ~2.87V with 340mV p-p ripple
    at 150kHz (switching regulator noise). Classic regulator-near-limit scenario.
    """
    n = int(sample_rate * duration_s)
    t = np.linspace(0, duration_s, n)
    signal = (
        dc_level
        + ripple_amplitude * np.sin(2 * np.pi * ripple_freq * t)
        + noise_std * np.random.randn(n)
    )
    return signal


def sim_clean_3v3_rail(
    sample_rate: float = 1_000_000,
    duration_s: float = 0.01,
) -> np.ndarray:
    """Simulate a healthy 3.3V rail — should produce all-PASS."""
    n = int(sample_rate * duration_s)
    t = np.linspace(0, duration_s, n)
    signal = 3.3 + 0.01 * np.sin(2 * np.pi * 50 * t) + 0.005 * np.random.randn(n)
    return signal


def sim_can_bus_healthy(
    sample_rate: float = 10_000_000,
    duration_s: float = 0.001,
    bit_rate: float = 500_000,
) -> tuple[np.ndarray, np.ndarray]:
    """Simulate healthy CAN bus with correct differential levels."""
    n = int(sample_rate * duration_s)
    t = np.linspace(0, duration_s, n)
    bit_period = 1.0 / bit_rate
    samples_per_bit = int(sample_rate * bit_period)

    # Generate random dominant/recessive pattern
    can_h = np.full(n, 2.5)  # recessive: CAN_H = CAN_L = 2.5V
    can_l = np.full(n, 2.5)

    for i in range(0, n, samples_per_bit):
        if np.random.random() > 0.4:  # 60% dominant bits
            end = min(i + samples_per_bit, n)
            can_h[i:end] = 3.5  # dominant: CAN_H = 3.5V
            can_l[i:end] = 1.5  # dominant: CAN_L = 1.5V

    # Add noise
    can_h += 0.05 * np.random.randn(n)
    can_l += 0.05 * np.random.randn(n)
    return can_h, can_l


def sim_can_bus_bad_termination(
    sample_rate: float = 10_000_000,
    duration_s: float = 0.001,
    bit_rate: float = 500_000,
) -> tuple[np.ndarray, np.ndarray]:
    """Simulate CAN bus with missing termination — excessive differential voltage + ringing."""
    n = int(sample_rate * duration_s)
    t = np.linspace(0, duration_s, n)
    bit_period = 1.0 / bit_rate
    samples_per_bit = int(sample_rate * bit_period)

    can_h = np.full(n, 2.5)
    can_l = np.full(n, 2.5)

    for i in range(0, n, samples_per_bit):
        if np.random.random() > 0.4:
            end = min(i + samples_per_bit, n)
            can_h[i:end] = 4.2   # too high — no termination
            can_l[i:end] = 0.8   # too low
            # Add ringing at transitions
            ring_len = min(10, end - i)
            for k in range(ring_len):
                decay = 0.5 * np.exp(-k / 3)
                can_h[i + k] += decay * ((-1) ** k)
                can_l[i + k] -= decay * ((-1) ** k)

    can_h += 0.08 * np.random.randn(n)
    can_l += 0.08 * np.random.randn(n)
    return can_h, can_l


def sim_brownout_serial_log() -> str:
    """Simulate serial output showing a brownout reset."""
    return """
ESP-ROM:esp32s3-20210327
Build:Mar 27 2021
rst:0x1 (POWERON),boot:0x8 (SPI_FAST_FLASH_BOOT)
I (24) boot: chip revision: v0.1
I (312) wifi: wifi firmware version: 2.0
I (424) wifi: Init data frame dynamic rx buffer num: 32
Brownout detector was triggered
ets Jul 29 2019 12:21:46
rst:0x3 (RTC_SW_SYS_RST),boot:0x8 (SPI_FAST_FLASH_BOOT)
Brownout detector was triggered
ets Jul 29 2019 12:21:46
rst:0x3 (RTC_SW_SYS_RST),boot:0x8 (SPI_FAST_FLASH_BOOT)
""".strip()


def sim_i2c_timeout_log() -> str:
    """Simulate serial output showing I2C NACK errors."""
    return """
I (312) main: Initializing I2C master on SDA=8 SCL=9 freq=400000
I (315) i2c: I2C master initialized
I (320) main: Scanning I2C bus...
I (325) main: Found device at 0x55
I (330) main: Reading register 0x00 from 0x55
E (835) i2c: I2C timeout - slave NACK on address 0x55
E (1340) i2c: I2C timeout - slave NACK on address 0x55
E (1845) i2c: I2C timeout - slave NACK on address 0x55
W (1850) main: I2C read failed after 3 retries
""".strip()


# ---------------------------------------------------------------------------
# Test scenarios
# ---------------------------------------------------------------------------

def run_scenario(name: str, description: str, func) -> bool:
    """Run a test scenario and report results."""
    print(f"\n{'='*70}")
    print(f"SCENARIO: {name}")
    print(f"  {description}")
    print(f"{'='*70}")

    try:
        result = func()
        print(f"\n  ✅ {name} — PASSED")
        return True
    except Exception as e:
        print(f"\n  ❌ {name} — FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def scenario_droopy_voltage_rail():
    """Test: 3.3V rail drooped to 2.87V with high ripple."""
    session = RCAPipeline.create_session(
        test_goal="Verify 3.3V rail stability under load",
        test_point="U3_output_3V3",
    )

    spec = ThresholdSpec(
        dc_voltage=3.3,
        dc_tolerance_pct=5.0,
        max_ripple_mv=100.0,
        max_rise_time_ns=10000.0,
        max_settling_time_us=50.0,
    )

    waveform = sim_droopy_3v3_rail()
    result = RCAPipeline.run_analysis(
        session,
        waveform_samples=waveform,
        sample_rate=1_000_000,
        spec=spec,
        psu_voltage=4.8,
        psu_current=0.35,
        serial_log=sim_brownout_serial_log(),
    )

    print(f"\n  Session: {json.dumps(result['session'], indent=2)}")
    print(f"\n  Overall verdict: {result['overall_verdict']}")
    print(f"\n  Failed metrics:")
    for m in result['failed_metrics']:
        print(f"    ❌ {m['name']}: {m['value']} {m['unit']} — {m['detail']}")

    print(f"\n  Hypotheses (top 3):")
    for i, h in enumerate(result['hypotheses'][:3], 1):
        print(f"    {i}. [{h['confidence_pct']:.0f}%] {h['description']}")
        for e in h['evidence'][:2]:
            print(f"       - {e}")

    print(f"\n  LLM escalation needed: {result['needs_llm_escalation']}")

    # Assertions
    assert result['overall_verdict'] == 'FAIL', "Should be FAIL verdict"
    assert len(result['failed_metrics']) >= 2, "Should have ≥2 failed metrics"
    assert len(result['hypotheses']) >= 2, "Should generate hypotheses"
    assert any('brownout' in h['description'].lower() for h in result['hypotheses']), \
        "Should detect brownout from serial log"

    # Generate report
    report_result = RCAPipeline.generate_report(session, "resolved")
    print(f"\n  --- REPORT (markdown preview, first 30 lines) ---")
    md_lines = report_result['report_markdown'].split('\n')
    for line in md_lines[:30]:
        print(f"  {line}")
    if len(md_lines) > 30:
        print(f"  ... ({len(md_lines) - 30} more lines)")

    return result


def scenario_healthy_rail():
    """Test: Clean 3.3V rail — should produce all-PASS."""
    session = RCAPipeline.create_session(
        test_goal="Verify 3.3V rail nominal operation",
        test_point="U3_output_3V3",
    )

    spec = ThresholdSpec(dc_voltage=3.3, dc_tolerance_pct=5.0, max_ripple_mv=100.0)
    waveform = sim_clean_3v3_rail()

    result = RCAPipeline.run_analysis(
        session,
        waveform_samples=waveform,
        sample_rate=1_000_000,
        spec=spec,
        psu_voltage=5.0,
        psu_current=0.08,
    )

    print(f"\n  Overall verdict: {result['overall_verdict']}")
    print(f"  Failed metrics: {len(result['failed_metrics'])}")
    print(f"  Hypotheses: {len(result['hypotheses'])}")

    assert result['overall_verdict'] == 'PASS', f"Should be PASS, got {result['overall_verdict']}"
    assert len(result['failed_metrics']) == 0, "Should have 0 failed metrics"
    assert len(result['hypotheses']) == 0, "Healthy rail should have no hypotheses"

    return result


def scenario_can_bus_healthy():
    """Test: Healthy CAN bus — should pass."""
    session = RCAPipeline.create_session(
        test_goal="Verify CAN bus communication",
        test_point="CAN_bus",
    )

    spec = ThresholdSpec()
    can_h, can_l = sim_can_bus_healthy()

    result = RCAPipeline.run_analysis(
        session,
        can_h_samples=can_h,
        can_l_samples=can_l,
        sample_rate=10_000_000,
        spec=spec,
    )

    print(f"\n  Overall verdict: {result['overall_verdict']}")
    for a in result['signal_analyses']:
        print(f"  Test point: {a['test_point']}")
        for m in a['metrics']:
            icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}[m['verdict']]
            print(f"    {icon} {m['name']}: {m['value']} {m['unit']}")

    assert result['overall_verdict'] in ('PASS', 'WARN'), "Healthy CAN should pass"
    return result


def scenario_can_bus_bad_termination():
    """Test: CAN bus with missing termination — should detect issue."""
    session = RCAPipeline.create_session(
        test_goal="Diagnose CAN bus communication failure",
        test_point="CAN_bus",
    )

    spec = ThresholdSpec()
    can_h, can_l = sim_can_bus_bad_termination()

    result = RCAPipeline.run_analysis(
        session,
        can_h_samples=can_h,
        can_l_samples=can_l,
        sample_rate=10_000_000,
        spec=spec,
    )

    print(f"\n  Overall verdict: {result['overall_verdict']}")
    print(f"\n  Failed metrics:")
    for m in result['failed_metrics']:
        print(f"    ❌ {m['name']}: {m['value']} {m['unit']} — {m['detail']}")

    print(f"\n  Hypotheses:")
    for i, h in enumerate(result['hypotheses'][:3], 1):
        print(f"    {i}. [{h['confidence_pct']:.0f}%] {h['description']}")

    assert result['overall_verdict'] == 'FAIL', "Bad termination should FAIL"
    assert len(result['hypotheses']) >= 1, "Should generate hypotheses"

    return result


def scenario_i2c_timeout():
    """Test: I2C timeout with serial log only (no waveform)."""
    session = RCAPipeline.create_session(
        test_goal="Diagnose I2C communication failure",
        test_point="I2C_SDA_SCL",
    )

    result = RCAPipeline.run_analysis(
        session,
        serial_log=sim_i2c_timeout_log(),
    )

    print(f"\n  Overall verdict: {result['overall_verdict']}")
    print(f"\n  Hypotheses:")
    for i, h in enumerate(result['hypotheses'][:3], 1):
        print(f"    {i}. [{h['confidence_pct']:.0f}%] {h['description']}")
        for e in h['evidence'][:2]:
            print(f"       - {e}")

    assert len(result['hypotheses']) >= 1, "Should detect I2C issue from log"
    assert any('i2c' in h['description'].lower() for h in result['hypotheses']), \
        "Should have I2C-related hypothesis"

    return result


def scenario_multi_iteration():
    """Test: Multiple iterations of the feedback loop."""
    session = RCAPipeline.create_session(
        test_goal="Diagnose 3.3V rail droop through iterative testing",
        test_point="U3_output_3V3",
        max_iterations=3,
    )

    spec = ThresholdSpec(dc_voltage=3.3, dc_tolerance_pct=5.0, max_ripple_mv=100.0)

    # Iteration 1: droopy rail, no serial log yet
    print("\n  --- Iteration 1: Initial measurement ---")
    waveform1 = sim_droopy_3v3_rail(dc_level=2.87, ripple_amplitude=0.17)
    result1 = RCAPipeline.run_analysis(
        session, waveform_samples=waveform1, sample_rate=1_000_000, spec=spec,
    )
    print(f"  Verdict: {result1['overall_verdict']}")
    print(f"  Top hypothesis: {result1['hypotheses'][0]['description'] if result1['hypotheses'] else 'none'}")
    assert result1['session']['iteration'] == 1

    # Iteration 2: added PSU data + serial log
    print("\n  --- Iteration 2: Added PSU telemetry + serial log ---")
    result2 = RCAPipeline.run_analysis(
        session,
        waveform_samples=sim_droopy_3v3_rail(dc_level=2.90, ripple_amplitude=0.15),
        sample_rate=1_000_000,
        spec=spec,
        psu_voltage=4.8,
        psu_current=0.42,
        serial_log=sim_brownout_serial_log(),
    )
    print(f"  Verdict: {result2['overall_verdict']}")
    print(f"  Top hypothesis: {result2['hypotheses'][0]['description'] if result2['hypotheses'] else 'none'}")
    assert result2['session']['iteration'] == 2

    # Iteration 3: max iterations → report generated
    print("\n  --- Iteration 3: Final iteration → auto-report ---")
    result3 = RCAPipeline.run_analysis(
        session,
        waveform_samples=sim_droopy_3v3_rail(dc_level=2.92, ripple_amplitude=0.14),
        sample_rate=1_000_000,
        spec=spec,
        psu_voltage=4.8,
        psu_current=0.40,
    )
    print(f"  Session status: {result3['session']['status']}")

    # Session should now be at max iterations, next call should generate report
    result4 = RCAPipeline.run_analysis(session)
    assert 'report_markdown' in result4, "Should get final report at max iterations"
    print(f"\n  Final report generated ({len(result4['report_markdown'])} chars)")

    return result4


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("BenchCI Root Cause Analysis — Simulated Verification Suite")
    print("=" * 70)

    scenarios = [
        ("Droopy 3.3V Rail", "3.3V rail drooped to 2.87V with brownout resets", scenario_droopy_voltage_rail),
        ("Healthy 3.3V Rail", "Clean 3.3V rail — should produce all-PASS", scenario_healthy_rail),
        ("Healthy CAN Bus", "Normal CAN bus with correct levels", scenario_can_bus_healthy),
        ("CAN Bad Termination", "CAN bus with missing 120Ω termination", scenario_can_bus_bad_termination),
        ("I2C Timeout (Log Only)", "I2C NACK errors detected from serial log", scenario_i2c_timeout),
        ("Multi-Iteration Loop", "3 iterations of the feedback loop → final report", scenario_multi_iteration),
    ]

    results = []
    for name, desc, func in scenarios:
        passed = run_scenario(name, desc, func)
        results.append((name, passed))

    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    total = len(results)
    passed = sum(1 for _, p in results if p)
    for name, p in results:
        icon = "✅" if p else "❌"
        print(f"  {icon} {name}")
    print(f"\n  {passed}/{total} scenarios passed")
    print(f"{'='*70}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
