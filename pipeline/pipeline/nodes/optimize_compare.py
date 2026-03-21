"""Optimize pipeline — Stage 5: Compare baseline vs optimized and produce report."""

from __future__ import annotations

from pipeline.callbacks import emit_event, update_run_status, check_run_status, store_diagnosis
from pipeline.state import OptimizePipelineState


async def compare_node(state: OptimizePipelineState) -> dict:
    run_id = state["run_id"]

    status = await check_run_status(run_id)
    if status in ("cancelled",):
        return {"status": status}

    await update_run_status(run_id, "running", "compare")

    baseline = state.get("baseline_result", {})
    optimized = state.get("optimized_result", {})
    analysis = state.get("analysis", {})
    isa_patterns = state.get("isa_patterns_used", [])
    rationale = state.get("optimization_rationale", "")

    b_exec = baseline.get("execution", {})
    o_exec = optimized.get("execution", {})
    b_power = baseline.get("power", {})
    o_power = optimized.get("power", {})

    # Compute speedup
    b_time = b_exec.get("per_iteration_us", 0)
    o_time = o_exec.get("per_iteration_us", 0)
    speedup = b_time / o_time if o_time > 0 else 0

    # Compute power reduction
    b_energy = b_power.get("energy_per_iter_uj", 0)
    o_energy = o_power.get("energy_per_iter_uj", 0)
    power_reduction_pct = ((b_energy - o_energy) / b_energy * 100) if b_energy > 0 else 0

    # Correctness check (from ESP32 reports)
    b_report = baseline.get("esp32_report", {})
    o_report = optimized.get("esp32_report", {})
    b_result = b_report.get("result")
    o_result = o_report.get("result")

    correctness = "unknown"
    if b_result is not None and o_result is not None:
        if isinstance(b_result, (int, float)) and isinstance(o_result, (int, float)):
            if abs(b_result - o_result) < 1e-4:
                correctness = "bit-exact" if b_result == o_result else "within tolerance (1e-4)"
            else:
                correctness = f"MISMATCH: baseline={b_result}, optimized={o_result}"
        elif b_result == o_result:
            correctness = "exact match"
        else:
            correctness = f"MISMATCH: baseline={b_result}, optimized={o_result}"

    comparison = {
        "speedup_x": round(speedup, 2),
        "baseline_us_per_iter": round(b_time, 2),
        "optimized_us_per_iter": round(o_time, 2),
        "power_reduction_pct": round(power_reduction_pct, 1),
        "baseline_energy_uj": round(b_energy, 3),
        "optimized_energy_uj": round(o_energy, 3),
        "correctness": correctness,
        "isa_patterns_used": isa_patterns,
        "summary": (
            f"{speedup:.1f}x speedup ({b_time:.1f}us → {o_time:.1f}us per iteration). "
            f"Energy: {power_reduction_pct:.0f}% reduction. "
            f"Correctness: {correctness}. "
            f"ISA patterns: {', '.join(isa_patterns)}."
        ),
    }

    # Store as a diagnosis (reuse the diagnoses table for the final report)
    await store_diagnosis(
        run_id,
        model="benchagent",
        summary=comparison["summary"],
        root_cause=rationale[:500] if rationale else None,
        confidence=1.0 if "MISMATCH" not in correctness else 0.5,
        suggested_fix={"isa_patterns": isa_patterns},
    )

    verdict = "passed" if speedup > 1.0 and "MISMATCH" not in correctness else "failed"

    await emit_event(run_id, "compare", "success" if verdict == "passed" else "warning",
                     comparison["summary"])

    return {
        "comparison": comparison,
        "status": verdict,
        "current_stage": "complete",
    }
