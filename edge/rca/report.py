"""
RCA Report Generator

Produces structured root cause analysis reports in both dict and
human-readable markdown format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from .signal_processing import SignalAnalysis, Verdict

if TYPE_CHECKING:
    from .context_analyzer import Hypothesis
    from .orchestrator import Iteration


# ---------------------------------------------------------------------------
# Report data structure
# ---------------------------------------------------------------------------

@dataclass
class RCAReport:
    session_id: str
    test_goal: str
    test_point: str
    board: str
    total_iterations: int
    resolution: str  # "resolved", "max_iterations", "escalated"
    root_cause: Optional[str] = None
    root_cause_confidence: Optional[float] = None
    root_cause_category: Optional[str] = None
    observations: list[dict] = field(default_factory=list)
    signal_summaries: list[dict] = field(default_factory=list)
    hypothesis_ranking: list[dict] = field(default_factory=list)
    recommended_actions: list[dict] = field(default_factory=list)
    decision_tree: list[dict] = field(default_factory=list)
    iteration_log: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "test_goal": self.test_goal,
            "test_point": self.test_point,
            "board": self.board,
            "total_iterations": self.total_iterations,
            "resolution": self.resolution,
            "root_cause": self.root_cause,
            "root_cause_confidence": self.root_cause_confidence,
            "root_cause_category": self.root_cause_category,
            "observations": self.observations,
            "signal_summaries": self.signal_summaries,
            "hypothesis_ranking": self.hypothesis_ranking,
            "recommended_actions": self.recommended_actions,
            "decision_tree": self.decision_tree,
            "iteration_log": self.iteration_log,
        }

    def to_markdown(self) -> str:
        """Render the report as a human-readable markdown string."""
        lines = []
        lines.append(f"# Root Cause Analysis Report — Session {self.session_id}")
        lines.append("")
        lines.append(f"**Board:** {self.board}")
        lines.append(f"**Test Goal:** {self.test_goal}")
        lines.append(f"**Test Point:** {self.test_point}")
        lines.append(f"**Iterations:** {self.total_iterations}")
        lines.append(f"**Resolution:** {self.resolution}")
        lines.append("")

        # --- Observation ---------------------------------------------------
        lines.append("## Observation")
        lines.append("")
        for obs in self.observations:
            lines.append(f"| Parameter | Value |")
            lines.append(f"|-----------|-------|")
            for k, v in obs.items():
                lines.append(f"| {k} | {v} |")
            lines.append("")

        # --- Signal Analysis -----------------------------------------------
        if self.signal_summaries:
            lines.append("## Signal Analysis")
            lines.append("")
            for summary in self.signal_summaries:
                tp = summary.get("test_point", "unknown")
                lines.append(f"### {tp}")
                lines.append("")
                lines.append("| Metric | Value | Unit | Verdict | Detail |")
                lines.append("|--------|-------|------|---------|--------|")
                for m in summary.get("metrics", []):
                    icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(m["verdict"], "")
                    lines.append(
                        f"| {m['name']} | {m['value']} | {m['unit']} | {icon} {m['verdict']} | {m['detail']} |"
                    )
                lines.append("")

        # --- Hypotheses ----------------------------------------------------
        if self.hypothesis_ranking:
            lines.append("## Hypotheses (Ranked)")
            lines.append("")
            for i, h in enumerate(self.hypothesis_ranking, 1):
                conf = h.get("confidence_pct", 0)
                lines.append(f"### {i}. [{conf:.0f}%] {h['description']}")
                lines.append(f"**Category:** {h.get('category', 'unknown')}")
                lines.append("")
                if h.get("evidence"):
                    lines.append("**Evidence:**")
                    for e in h["evidence"]:
                        lines.append(f"- {e}")
                    lines.append("")
                if h.get("verification_steps"):
                    lines.append("**Verification Steps:**")
                    for s in h["verification_steps"]:
                        lines.append(f"- {s}")
                    lines.append("")

        # --- Root Cause ----------------------------------------------------
        if self.root_cause:
            lines.append("## Root Cause")
            lines.append("")
            lines.append(f"**{self.root_cause}**")
            lines.append(f"- Confidence: {self.root_cause_confidence:.0f}%")
            lines.append(f"- Category: {self.root_cause_category}")
            lines.append("")

        # --- Recommended Actions -------------------------------------------
        if self.recommended_actions:
            lines.append("## Recommended Actions")
            lines.append("")
            for a in self.recommended_actions:
                prio = a.get("priority", "-")
                atype = a.get("action_type", "")
                lines.append(f"{prio}. **[{atype}]** {a['description']}")
            lines.append("")

        # --- Decision Tree -------------------------------------------------
        if self.decision_tree:
            lines.append("## Decision Tree (Next Steps)")
            lines.append("")
            lines.append("```")
            for node in self.decision_tree:
                condition = node.get("condition", "")
                result = node.get("result", "")
                lines.append(f"IF {condition}")
                lines.append(f"  → {result}")
            lines.append("```")
            lines.append("")

        # --- Iteration Log -------------------------------------------------
        if self.iteration_log:
            lines.append("## Iteration Log")
            lines.append("")
            for entry in self.iteration_log:
                num = entry.get("iteration", "?")
                lines.append(f"### Iteration {num}")
                if entry.get("analyses"):
                    lines.append(f"- Analyses: {len(entry['analyses'])} test points evaluated")
                if entry.get("top_hypothesis"):
                    lines.append(f"- Top hypothesis: {entry['top_hypothesis']}")
                if entry.get("actions"):
                    lines.append(f"- Actions taken: {len(entry['actions'])}")
                    for a in entry["actions"]:
                        lines.append(f"  - {a}")
                lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Report generator
# ---------------------------------------------------------------------------

class RCAReportGenerator:

    @staticmethod
    def generate(
        session_id: str,
        test_goal: str,
        test_point: str,
        board: str,
        iterations: list[Iteration],
        hypotheses: list[Hypothesis],
        signal_analyses: list[SignalAnalysis],
        resolution_reason: str,
    ) -> RCAReport:
        report = RCAReport(
            session_id=session_id,
            test_goal=test_goal,
            test_point=test_point,
            board=board,
            total_iterations=len(iterations),
            resolution=resolution_reason,
        )

        # --- Root cause from top hypothesis --------------------------------
        if hypotheses:
            top = hypotheses[0]
            report.root_cause = top.description
            report.root_cause_confidence = top.confidence_pct
            report.root_cause_category = top.category

        # --- Observations --------------------------------------------------
        for analysis in signal_analyses:
            obs = {"Test Point": analysis.test_point}
            for m in analysis.metrics:
                if m.verdict in (Verdict.FAIL, Verdict.WARN):
                    obs[m.name] = f"{m.value} {m.unit} ({m.verdict.value})"
                elif m.expected_min is not None or m.expected_max is not None:
                    exp_str = ""
                    if m.expected_min is not None and m.expected_max is not None:
                        exp_str = f"expected {m.expected_min}–{m.expected_max} {m.unit}"
                    elif m.expected_max is not None:
                        exp_str = f"expected ≤ {m.expected_max} {m.unit}"
                    obs[m.name] = f"{m.value} {m.unit} ✅ ({exp_str})"
            report.observations.append(obs)

        # --- Signal summaries ----------------------------------------------
        for analysis in signal_analyses:
            report.signal_summaries.append(analysis.to_dict())

        # --- Hypothesis ranking --------------------------------------------
        for h in hypotheses[:5]:
            report.hypothesis_ranking.append(h.to_dict())

        # --- Recommended actions from hypotheses ---------------------------
        if hypotheses:
            priority = 1
            for step in hypotheses[0].verification_steps:
                step_lower = step.lower()
                if step_lower.startswith("firmware:"):
                    atype = "FIRMWARE_FIX"
                elif step_lower.startswith("hardware:"):
                    atype = "HARDWARE_INSTRUCTION"
                elif step_lower.startswith("probe:") or step_lower.startswith("instrument:"):
                    atype = "PROBE_REQUEST"
                elif step_lower.startswith("measure:"):
                    atype = "INSTRUMENT_ADJUST"
                else:
                    atype = "GENERAL"
                report.recommended_actions.append({
                    "priority": priority,
                    "action_type": atype,
                    "description": step,
                })
                priority += 1

        # --- Decision tree -------------------------------------------------
        report.decision_tree = RCAReportGenerator._build_decision_tree(
            hypotheses, signal_analyses,
        )

        # --- Iteration log -------------------------------------------------
        for it in iterations:
            entry = {
                "iteration": it.iteration_num,
                "analyses": [a.test_point for a in it.signal_analyses],
                "top_hypothesis": it.hypotheses[0].description if it.hypotheses else None,
                "actions": [],
            }
            report.iteration_log.append(entry)

        return report

    @staticmethod
    def _build_decision_tree(
        hypotheses: list[Hypothesis],
        analyses: list[SignalAnalysis],
    ) -> list[dict]:
        """Build if/then decision nodes based on current hypotheses."""
        tree: list[dict] = []

        # Extract key measurements for conditional branching
        has_voltage_fail = False
        has_current_fail = False
        has_ripple_fail = False

        for analysis in analyses:
            for m in analysis.metrics:
                if m.verdict == Verdict.FAIL:
                    if m.name == "dc_voltage" or m.name == "supply_voltage":
                        has_voltage_fail = True
                    if m.name == "load_current":
                        has_current_fail = True
                    if m.name == "ripple_voltage":
                        has_ripple_fail = True

        if has_voltage_fail:
            tree.append({
                "condition": "VIN (regulator input) < 4.5V",
                "result": "Problem is upstream — check USB power source or PSU configuration",
            })
            tree.append({
                "condition": "VIN ≥ 4.5V AND I_load > 500mA",
                "result": "Board drawing excessive current — check for short circuits or reduce peripheral usage",
            })
            tree.append({
                "condition": "VIN ≥ 4.5V AND I_load ≤ 500mA",
                "result": "Regulator may be damaged — measure regulator case temperature, consider replacement",
            })

        if has_ripple_fail and not has_voltage_fail:
            tree.append({
                "condition": "Ripple frequency matches switching regulator",
                "result": "Add input filtering (ferrite bead + cap) between switcher and LDO",
            })
            tree.append({
                "condition": "Ripple frequency is load-dependent",
                "result": "Add bulk decoupling (47μF+) near load, check ESR of existing caps",
            })

        if has_current_fail:
            tree.append({
                "condition": "Current drops after disabling WiFi/BT",
                "result": "Normal operation — increase PSU current limit or use higher-rated regulator",
            })
            tree.append({
                "condition": "Current remains high with all peripherals disabled",
                "result": "Short circuit on board — inspect solder joints and check for bridged pins",
            })

        if not tree:
            # Generic fallback
            tree.append({
                "condition": "All metrics pass after fix",
                "result": "Root cause confirmed — document and close",
            })
            tree.append({
                "condition": "Metrics still failing after fix attempt",
                "result": "Re-run RCA with additional probe points",
            })

        return tree
