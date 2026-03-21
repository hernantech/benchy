"""
Tier 3 — RCA Orchestrator (Pipeline Mode)

This is NOT a separate decision-making agent. The Gemini chat agent in the
UI IS the Tier 3 decision maker. This module serves as:

  1. A session manager — tracks iteration state across the feedback loop
  2. A data pipeline — runs Tier 1 (signal processing) + Tier 2 (context
     analysis) and packages the results into structured JSON that the
     Gemini agent receives as a tool result
  3. A report generator — produces the final RCA report when Gemini decides
     the root cause is found

The Gemini agent calls `analyze_rca` as a tool → this module runs the
pipeline → returns structured hypotheses + metrics → Gemini reasons about
them and decides what to do next (probe, fix firmware, instruct user, etc.)

Architecture:
  User ↔ Chat UI ↔ Gemini Agent (Tier 3 = decision maker)
                        ↓ tool call
                    RPi Worker → /rca/analyze endpoint
                        ↓
                    Tier 1: SignalProcessor (EE calculations)
                        ↓
                    Tier 2: ContextAnalyzer (hypothesis generation)
                        ↓
                    Structured JSON response → back to Gemini
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from .signal_processing import SignalAnalysis, SignalProcessor, ThresholdSpec, Verdict
from .context_analyzer import ContextAnalyzer, Hypothesis
from .report import RCAReportGenerator, RCAReport


# ---------------------------------------------------------------------------
# Iteration record — one cycle of the feedback loop
# ---------------------------------------------------------------------------

@dataclass
class Iteration:
    iteration_num: int
    timestamp: float
    signal_analyses: list[SignalAnalysis] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    serial_log: Optional[str] = None
    firmware_source: Optional[str] = None
    notes: str = ""


# ---------------------------------------------------------------------------
# RCA Session — tracks the full feedback loop
# ---------------------------------------------------------------------------

@dataclass
class RCASession:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    test_goal: str = ""
    test_point: str = ""
    board: str = "ESP32-S3-DevKitC-1"
    max_iterations: int = 5
    iterations: list[Iteration] = field(default_factory=list)
    status: str = "active"  # active, resolved, escalated, max_iterations_reached
    final_report: Optional[RCAReport] = None

    @property
    def current_iteration(self) -> int:
        return len(self.iterations)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "test_goal": self.test_goal,
            "test_point": self.test_point,
            "board": self.board,
            "iteration": self.current_iteration,
            "max_iterations": self.max_iterations,
            "status": self.status,
        }


# ---------------------------------------------------------------------------
# RCA Pipeline — runs Tier 1 + Tier 2, returns structured data for Gemini
# ---------------------------------------------------------------------------

class RCAPipeline:
    """
    Runs the signal processing + context analysis pipeline.
    Returns structured JSON that the Gemini chat agent (Tier 3) uses to
    make decisions. Gemini is the orchestrator — this is just the analysis.

    Usage in the edge worker:
        session_store = {}  # in-memory for now

        @app.post("/rca/analyze")
        async def rca_analyze(req):
            session = session_store.get(req.session_id) or RCAPipeline.create_session(...)
            result = RCAPipeline.run_analysis(session, ...)
            session_store[session.session_id] = session
            return result
    """

    # ----- Session management ----------------------------------------------

    @staticmethod
    def create_session(
        test_goal: str,
        test_point: str,
        board: str = "ESP32-S3-DevKitC-1",
        max_iterations: int = 5,
    ) -> RCASession:
        return RCASession(
            test_goal=test_goal,
            test_point=test_point,
            board=board,
            max_iterations=max_iterations,
        )

    # ----- Main analysis pipeline ------------------------------------------

    @staticmethod
    def run_analysis(
        session: RCASession,
        waveform_samples: Optional[object] = None,
        sample_rate: float = 1_000_000,
        spec: Optional[ThresholdSpec] = None,
        psu_voltage: Optional[float] = None,
        psu_current: Optional[float] = None,
        serial_log: Optional[str] = None,
        firmware_source: Optional[str] = None,
        can_h_samples: Optional[object] = None,
        can_l_samples: Optional[object] = None,
        expected_psu_voltage: float = 5.0,
        max_psu_current: float = 0.5,
    ) -> dict:
        """
        Run Tier 1 + Tier 2 analysis pipeline. Returns a structured dict
        that the Gemini agent receives as a tool result.

        The dict contains:
          - session: current session state
          - metrics: all computed metrics with verdicts
          - hypotheses: ranked list of possible root causes
          - needs_llm_escalation: True if confidence is low
          - llm_prompt: pre-built prompt for LLM escalation (if needed)
          - report: final report (only if max iterations reached)
        """
        import numpy as np

        if session.status != "active":
            return {
                "error": f"Session {session.session_id} is {session.status}",
                "session": session.to_dict(),
            }

        if session.current_iteration >= session.max_iterations:
            session.status = "max_iterations_reached"
            report = RCAPipeline._generate_report(session, "max_iterations")
            session.final_report = report
            return {
                "session": session.to_dict(),
                "report": report.to_dict(),
                "report_markdown": report.to_markdown(),
            }

        iteration = Iteration(
            iteration_num=session.current_iteration + 1,
            timestamp=time.time(),
            serial_log=serial_log,
            firmware_source=firmware_source,
        )

        if spec is None:
            spec = ThresholdSpec()

        # ----- Tier 1: Signal Processing -----------------------------------
        analyses: list[SignalAnalysis] = []

        if waveform_samples is not None:
            arr = np.asarray(waveform_samples, dtype=np.float64)
            voltage_analysis = SignalProcessor.analyze_voltage_rail(
                arr, sample_rate, spec, test_point=session.test_point,
            )
            analyses.append(voltage_analysis)

        if can_h_samples is not None and can_l_samples is not None:
            can_analysis = SignalProcessor.analyze_can_bus(
                np.asarray(can_h_samples, dtype=np.float64),
                np.asarray(can_l_samples, dtype=np.float64),
                sample_rate, spec, test_point=f"{session.test_point}_can",
            )
            analyses.append(can_analysis)

        if psu_voltage is not None and psu_current is not None:
            power_analysis = SignalProcessor.analyze_power(
                psu_voltage, psu_current,
                expected_voltage=expected_psu_voltage,
                max_current=max_psu_current,
                test_point=f"{session.test_point}_psu",
            )
            analyses.append(power_analysis)

        iteration.signal_analyses = analyses

        # ----- Tier 2: Context Analysis ------------------------------------
        hypotheses = ContextAnalyzer.analyze(analyses, serial_log, firmware_source)
        iteration.hypotheses = hypotheses

        session.iterations.append(iteration)

        # ----- Package results for Gemini ----------------------------------
        needs_escalation = (
            not hypotheses
            or hypotheses[0].confidence_pct < 40
        )

        result: dict = {
            "session": session.to_dict(),
            "signal_analyses": [a.to_dict() for a in analyses],
            "hypotheses": [h.to_dict() for h in hypotheses[:5]],
            "overall_verdict": max(
                (a.overall_verdict for a in analyses),
                key=lambda v: {"PASS": 0, "WARN": 1, "FAIL": 2}.get(v.value, 0),
                default=Verdict.PASS,
            ).value if analyses else "NO_DATA",
            "failed_metrics": [
                m.to_dict()
                for a in analyses
                for m in a.failed_metrics()
            ],
            "needs_llm_escalation": needs_escalation,
        }

        # If low confidence, include pre-built prompt for Gemini to self-reason
        if needs_escalation:
            result["escalation_context"] = ContextAnalyzer.build_llm_prompt(
                analyses, hypotheses, serial_log,
            )

        return result

    # ----- Generate final report -------------------------------------------

    @staticmethod
    def generate_report(session: RCASession, reason: str = "resolved") -> dict:
        """
        Called by the Gemini agent (via tool) when it decides the root cause
        is found or wants to generate a summary report.
        """
        report = RCAPipeline._generate_report(session, reason)
        session.final_report = report
        session.status = reason
        return {
            "session": session.to_dict(),
            "report": report.to_dict(),
            "report_markdown": report.to_markdown(),
        }

    @staticmethod
    def _generate_report(session: RCASession, reason: str) -> RCAReport:
        all_hypotheses = []
        if session.iterations:
            all_hypotheses = session.iterations[-1].hypotheses

        all_analyses = []
        for it in session.iterations:
            all_analyses.extend(it.signal_analyses)

        return RCAReportGenerator.generate(
            session_id=session.session_id,
            test_goal=session.test_goal,
            test_point=session.test_point,
            board=session.board,
            iterations=session.iterations,
            hypotheses=all_hypotheses,
            signal_analyses=all_analyses,
            resolution_reason=reason,
        )
