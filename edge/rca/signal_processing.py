"""
Tier 1 — Signal Processing Pipeline

Deterministic EE calculations applied to raw oscilloscope and PSU data.
No LLM involved. Produces structured metrics with PASS/WARN/FAIL verdicts
by comparing against expected thresholds from datasheets or test specs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Verdict enum
# ---------------------------------------------------------------------------

class Verdict(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


# ---------------------------------------------------------------------------
# Metric result container
# ---------------------------------------------------------------------------

@dataclass
class MetricResult:
    name: str
    value: float
    unit: str
    expected_min: Optional[float] = None
    expected_max: Optional[float] = None
    verdict: Verdict = Verdict.PASS
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": round(self.value, 6),
            "unit": self.unit,
            "expected_min": self.expected_min,
            "expected_max": self.expected_max,
            "verdict": self.verdict.value,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# Threshold spec — defines what "good" looks like for a given test point
# ---------------------------------------------------------------------------

@dataclass
class ThresholdSpec:
    """Expected values for a measurement point."""
    dc_voltage: Optional[float] = None       # nominal DC level (V)
    dc_tolerance_pct: float = 5.0            # ± percentage around nominal
    max_ripple_mv: Optional[float] = None    # max acceptable Vpp ripple (mV)
    max_rise_time_ns: Optional[float] = None
    max_fall_time_ns: Optional[float] = None
    max_overshoot_pct: float = 10.0
    max_undershoot_pct: float = 10.0
    max_settling_time_us: Optional[float] = None
    # CAN bus specific
    can_diff_dominant_min: float = 1.5       # V — CAN differential dominant low bound
    can_diff_dominant_max: float = 3.0       # V — CAN differential dominant high bound
    can_diff_recessive_max: float = 0.5      # V — recessive should be near 0
    can_common_mode_min: float = 2.0
    can_common_mode_max: float = 3.0


# ---------------------------------------------------------------------------
# Analysis result bundle
# ---------------------------------------------------------------------------

@dataclass
class SignalAnalysis:
    test_point: str
    metrics: list[MetricResult] = field(default_factory=list)
    overall_verdict: Verdict = Verdict.PASS
    raw_stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "test_point": self.test_point,
            "overall_verdict": self.overall_verdict.value,
            "metrics": [m.to_dict() for m in self.metrics],
            "raw_stats": self.raw_stats,
        }

    def failed_metrics(self) -> list[MetricResult]:
        return [m for m in self.metrics if m.verdict == Verdict.FAIL]

    def warned_metrics(self) -> list[MetricResult]:
        return [m for m in self.metrics if m.verdict == Verdict.WARN]


# ---------------------------------------------------------------------------
# Signal Processor — core Tier 1 engine
# ---------------------------------------------------------------------------

class SignalProcessor:
    """
    Accepts raw waveform arrays and PSU telemetry, returns structured
    SignalAnalysis with every metric computed and verdict-tagged.
    """

    # ----- voltage / power rail analysis -----------------------------------

    @staticmethod
    def analyze_voltage_rail(
        samples: np.ndarray,
        sample_rate: float,
        spec: ThresholdSpec,
        test_point: str = "voltage_rail",
    ) -> SignalAnalysis:
        """Full analysis of a DC voltage rail waveform."""
        analysis = SignalAnalysis(test_point=test_point)
        arr = np.asarray(samples, dtype=np.float64)

        v_min = float(arr.min())
        v_max = float(arr.max())
        v_mean = float(arr.mean())
        v_pp = v_max - v_min
        v_rms = float(np.sqrt(np.mean(arr ** 2)))

        analysis.raw_stats = {
            "v_min": round(v_min, 6),
            "v_max": round(v_max, 6),
            "v_mean": round(v_mean, 6),
            "v_pp": round(v_pp, 6),
            "v_rms": round(v_rms, 6),
            "sample_count": len(arr),
            "sample_rate": sample_rate,
        }

        # --- DC level check ------------------------------------------------
        if spec.dc_voltage is not None:
            tol = spec.dc_voltage * spec.dc_tolerance_pct / 100.0
            exp_min = spec.dc_voltage - tol
            exp_max = spec.dc_voltage + tol
            delta_pct = abs(v_mean - spec.dc_voltage) / spec.dc_voltage * 100

            if exp_min <= v_mean <= exp_max:
                verdict = Verdict.PASS
                detail = f"DC level {v_mean:.3f}V within ±{spec.dc_tolerance_pct}% of {spec.dc_voltage}V"
            elif delta_pct < spec.dc_tolerance_pct * 1.5:
                verdict = Verdict.WARN
                detail = f"DC level {v_mean:.3f}V is {delta_pct:.1f}% off nominal {spec.dc_voltage}V (marginal)"
            else:
                verdict = Verdict.FAIL
                detail = f"DC level {v_mean:.3f}V is {delta_pct:.1f}% off nominal {spec.dc_voltage}V"

            analysis.metrics.append(MetricResult(
                name="dc_voltage",
                value=v_mean,
                unit="V",
                expected_min=exp_min,
                expected_max=exp_max,
                verdict=verdict,
                detail=detail,
            ))

        # --- Ripple check --------------------------------------------------
        ripple_mv = v_pp * 1000
        if spec.max_ripple_mv is not None:
            if ripple_mv <= spec.max_ripple_mv:
                verdict = Verdict.PASS
                detail = f"Ripple {ripple_mv:.1f}mV within limit {spec.max_ripple_mv}mV"
            elif ripple_mv <= spec.max_ripple_mv * 1.5:
                verdict = Verdict.WARN
                detail = f"Ripple {ripple_mv:.1f}mV approaching limit {spec.max_ripple_mv}mV"
            else:
                verdict = Verdict.FAIL
                detail = f"Ripple {ripple_mv:.1f}mV exceeds limit {spec.max_ripple_mv}mV"

            analysis.metrics.append(MetricResult(
                name="ripple_voltage",
                value=ripple_mv,
                unit="mV",
                expected_max=spec.max_ripple_mv,
                verdict=verdict,
                detail=detail,
            ))

        # --- Dominant frequency via FFT ------------------------------------
        if len(arr) >= 64:
            fft_result = np.fft.rfft(arr - v_mean)
            magnitudes = np.abs(fft_result)
            freqs = np.fft.rfftfreq(len(arr), d=1.0 / sample_rate)
            # skip DC bin
            if len(magnitudes) > 1:
                dominant_idx = np.argmax(magnitudes[1:]) + 1
                dominant_freq = float(freqs[dominant_idx])
                dominant_mag = float(magnitudes[dominant_idx])
                analysis.metrics.append(MetricResult(
                    name="dominant_frequency",
                    value=dominant_freq,
                    unit="Hz",
                    verdict=Verdict.PASS,
                    detail=f"Dominant ripple component at {dominant_freq/1000:.1f}kHz (magnitude {dominant_mag:.4f})",
                ))
                analysis.raw_stats["dominant_freq_hz"] = round(dominant_freq, 2)

        # --- Signal integrity (rise time, overshoot) -----------------------
        si_metrics = SignalProcessor.compute_signal_integrity(arr, sample_rate, spec)
        analysis.metrics.extend(si_metrics)

        # --- Roll up overall verdict ---------------------------------------
        if any(m.verdict == Verdict.FAIL for m in analysis.metrics):
            analysis.overall_verdict = Verdict.FAIL
        elif any(m.verdict == Verdict.WARN for m in analysis.metrics):
            analysis.overall_verdict = Verdict.WARN

        return analysis

    # ----- signal integrity (rise/fall time, overshoot) --------------------

    @staticmethod
    def compute_signal_integrity(
        arr: np.ndarray,
        sample_rate: float,
        spec: ThresholdSpec,
    ) -> list[MetricResult]:
        """Rise time, fall time, overshoot, undershoot, settling time."""
        metrics: list[MetricResult] = []
        dt = 1.0 / sample_rate

        v_min, v_max = float(arr.min()), float(arr.max())
        v_range = v_max - v_min
        if v_range < 0.05:
            return metrics  # flat/quiet signal, no meaningful transient to measure

        lo = v_min + 0.1 * v_range  # 10% level
        hi = v_min + 0.9 * v_range  # 90% level

        # --- Rise time (10% → 90%) ----------------------------------------
        rise_ns = 0.0
        for i in range(1, len(arr)):
            if arr[i - 1] <= lo < arr[i]:
                for j in range(i, len(arr)):
                    if arr[j] >= hi:
                        rise_ns = (j - i) * dt * 1e9
                        break
                break

        if rise_ns > 0 and spec.max_rise_time_ns is not None:
            verdict = Verdict.PASS if rise_ns <= spec.max_rise_time_ns else Verdict.FAIL
            metrics.append(MetricResult(
                name="rise_time",
                value=rise_ns,
                unit="ns",
                expected_max=spec.max_rise_time_ns,
                verdict=verdict,
                detail=f"Rise time {rise_ns:.1f}ns (limit {spec.max_rise_time_ns}ns)",
            ))
        elif rise_ns > 0:
            metrics.append(MetricResult(
                name="rise_time", value=rise_ns, unit="ns",
                detail=f"Rise time {rise_ns:.1f}ns (no limit specified)",
            ))

        # --- Fall time (90% → 10%) ----------------------------------------
        fall_ns = 0.0
        for i in range(1, len(arr)):
            if arr[i - 1] >= hi > arr[i]:
                for j in range(i, len(arr)):
                    if arr[j] <= lo:
                        fall_ns = (j - i) * dt * 1e9
                        break
                break

        if fall_ns > 0 and spec.max_fall_time_ns is not None:
            verdict = Verdict.PASS if fall_ns <= spec.max_fall_time_ns else Verdict.FAIL
            metrics.append(MetricResult(
                name="fall_time",
                value=fall_ns,
                unit="ns",
                expected_max=spec.max_fall_time_ns,
                verdict=verdict,
                detail=f"Fall time {fall_ns:.1f}ns (limit {spec.max_fall_time_ns}ns)",
            ))
        elif fall_ns > 0:
            metrics.append(MetricResult(
                name="fall_time", value=fall_ns, unit="ns",
                detail=f"Fall time {fall_ns:.1f}ns (no limit specified)",
            ))

        # --- Overshoot % ---------------------------------------------------
        # Overshoot: how far above the 90% level the signal goes
        v_steady = v_min + v_range  # assume final value ≈ v_max region
        overshoot_pct = max(0, (v_max - hi) / v_range * 100)
        verdict = Verdict.PASS if overshoot_pct <= spec.max_overshoot_pct else Verdict.FAIL
        metrics.append(MetricResult(
            name="overshoot",
            value=overshoot_pct,
            unit="%",
            expected_max=spec.max_overshoot_pct,
            verdict=verdict,
            detail=f"Overshoot {overshoot_pct:.1f}% (limit {spec.max_overshoot_pct}%)",
        ))

        # --- Undershoot % --------------------------------------------------
        undershoot_pct = max(0, (lo - v_min) / v_range * 100)
        verdict = Verdict.PASS if undershoot_pct <= spec.max_undershoot_pct else Verdict.FAIL
        metrics.append(MetricResult(
            name="undershoot",
            value=undershoot_pct,
            unit="%",
            expected_max=spec.max_undershoot_pct,
            verdict=verdict,
            detail=f"Undershoot {undershoot_pct:.1f}% (limit {spec.max_undershoot_pct}%)",
        ))

        # --- Settling time (to ±2% band of final value) --------------------
        if spec.max_settling_time_us is not None:
            final_value = float(np.mean(arr[-len(arr)//10:]))  # average of last 10%
            band = 0.02 * abs(final_value) if final_value != 0 else 0.02
            settling_idx = len(arr) - 1
            for i in range(len(arr) - 1, -1, -1):
                if abs(arr[i] - final_value) > band:
                    settling_idx = i
                    break
            settling_us = settling_idx * dt * 1e6
            verdict = Verdict.PASS if settling_us <= spec.max_settling_time_us else Verdict.FAIL
            metrics.append(MetricResult(
                name="settling_time",
                value=settling_us,
                unit="μs",
                expected_max=spec.max_settling_time_us,
                verdict=verdict,
                detail=f"Settling time {settling_us:.1f}μs to ±2% band (limit {spec.max_settling_time_us}μs)",
            ))

        return metrics

    # ----- CAN bus differential analysis -----------------------------------

    @staticmethod
    def analyze_can_bus(
        can_h_samples: np.ndarray,
        can_l_samples: np.ndarray,
        sample_rate: float,
        spec: ThresholdSpec,
        test_point: str = "can_bus",
    ) -> SignalAnalysis:
        """Analyze CAN bus differential and common-mode voltages."""
        analysis = SignalAnalysis(test_point=test_point)
        h = np.asarray(can_h_samples, dtype=np.float64)
        l = np.asarray(can_l_samples, dtype=np.float64)

        v_diff = h - l
        v_cm = (h + l) / 2.0

        diff_max = float(v_diff.max())
        diff_min = float(v_diff.min())
        cm_mean = float(v_cm.mean())

        analysis.raw_stats = {
            "can_h_mean": round(float(h.mean()), 4),
            "can_l_mean": round(float(l.mean()), 4),
            "v_diff_max": round(diff_max, 4),
            "v_diff_min": round(diff_min, 4),
            "v_cm_mean": round(cm_mean, 4),
        }

        # --- Dominant level check ------------------------------------------
        # During dominant state, V_diff should be 1.5V–3.0V
        dominant_samples = v_diff[v_diff > 0.5]  # rough threshold for dominant bits
        if len(dominant_samples) > 0:
            dom_mean = float(dominant_samples.mean())
            in_range = spec.can_diff_dominant_min <= dom_mean <= spec.can_diff_dominant_max
            analysis.metrics.append(MetricResult(
                name="can_dominant_differential",
                value=dom_mean,
                unit="V",
                expected_min=spec.can_diff_dominant_min,
                expected_max=spec.can_diff_dominant_max,
                verdict=Verdict.PASS if in_range else Verdict.FAIL,
                detail=f"Dominant V_diff={dom_mean:.3f}V (expected {spec.can_diff_dominant_min}–{spec.can_diff_dominant_max}V)",
            ))

        # --- Recessive level check -----------------------------------------
        recessive_samples = v_diff[v_diff <= 0.5]
        if len(recessive_samples) > 0:
            rec_mean = float(recessive_samples.mean())
            in_range = rec_mean <= spec.can_diff_recessive_max
            analysis.metrics.append(MetricResult(
                name="can_recessive_differential",
                value=rec_mean,
                unit="V",
                expected_max=spec.can_diff_recessive_max,
                verdict=Verdict.PASS if in_range else Verdict.FAIL,
                detail=f"Recessive V_diff={rec_mean:.3f}V (expected < {spec.can_diff_recessive_max}V)",
            ))

        # --- Common-mode voltage -------------------------------------------
        cm_ok = spec.can_common_mode_min <= cm_mean <= spec.can_common_mode_max
        analysis.metrics.append(MetricResult(
            name="can_common_mode",
            value=cm_mean,
            unit="V",
            expected_min=spec.can_common_mode_min,
            expected_max=spec.can_common_mode_max,
            verdict=Verdict.PASS if cm_ok else Verdict.WARN,
            detail=f"Common-mode {cm_mean:.3f}V (expected {spec.can_common_mode_min}–{spec.can_common_mode_max}V)",
        ))

        # --- Bit rate estimation -------------------------------------------
        # Count zero-crossings of (v_diff - threshold) to estimate bit rate
        threshold = 0.75  # halfway between recessive and dominant
        crossings = np.where(np.diff(np.sign(v_diff - threshold)))[0]
        if len(crossings) >= 2:
            avg_half_bit = np.mean(np.diff(crossings)) / sample_rate
            estimated_bit_rate = 1.0 / (2 * avg_half_bit) if avg_half_bit > 0 else 0
            analysis.metrics.append(MetricResult(
                name="estimated_bit_rate",
                value=estimated_bit_rate,
                unit="bps",
                detail=f"Estimated CAN bit rate: {estimated_bit_rate/1000:.1f} kbps",
            ))

        # --- Roll up -------------------------------------------------------
        if any(m.verdict == Verdict.FAIL for m in analysis.metrics):
            analysis.overall_verdict = Verdict.FAIL
        elif any(m.verdict == Verdict.WARN for m in analysis.metrics):
            analysis.overall_verdict = Verdict.WARN

        return analysis

    # ----- Power analysis from PSU telemetry -------------------------------

    @staticmethod
    def analyze_power(
        voltage: float,
        current: float,
        expected_voltage: float,
        max_current: float,
        test_point: str = "power_supply",
    ) -> SignalAnalysis:
        """Analyze PSU telemetry for load regulation and power budget."""
        analysis = SignalAnalysis(test_point=test_point)
        power = voltage * current

        analysis.raw_stats = {
            "voltage": round(voltage, 4),
            "current": round(current, 4),
            "power_w": round(power, 4),
        }

        # --- Voltage check -------------------------------------------------
        tol = expected_voltage * 0.05  # 5%
        v_ok = (expected_voltage - tol) <= voltage <= (expected_voltage + tol)
        delta_pct = abs(voltage - expected_voltage) / expected_voltage * 100
        analysis.metrics.append(MetricResult(
            name="supply_voltage",
            value=voltage,
            unit="V",
            expected_min=expected_voltage - tol,
            expected_max=expected_voltage + tol,
            verdict=Verdict.PASS if v_ok else Verdict.FAIL,
            detail=f"Supply {voltage:.3f}V vs expected {expected_voltage:.3f}V (Δ{delta_pct:.1f}%)",
        ))

        # --- Current check -------------------------------------------------
        i_ok = current <= max_current
        analysis.metrics.append(MetricResult(
            name="load_current",
            value=current * 1000,
            unit="mA",
            expected_max=max_current * 1000,
            verdict=Verdict.PASS if i_ok else Verdict.FAIL,
            detail=f"Load current {current*1000:.1f}mA (limit {max_current*1000:.1f}mA)",
        ))

        # --- Power budget --------------------------------------------------
        analysis.metrics.append(MetricResult(
            name="power_consumption",
            value=power * 1000,
            unit="mW",
            detail=f"Power consumption {power*1000:.1f}mW",
        ))

        if any(m.verdict == Verdict.FAIL for m in analysis.metrics):
            analysis.overall_verdict = Verdict.FAIL
        elif any(m.verdict == Verdict.WARN for m in analysis.metrics):
            analysis.overall_verdict = Verdict.WARN

        return analysis
