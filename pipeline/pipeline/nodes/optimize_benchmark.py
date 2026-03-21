"""Optimize pipeline — Stages 3+4: Run baseline and optimized benchmarks."""

from __future__ import annotations

from pipeline.callbacks import emit_event, update_run_status, check_run_status, store_measurement
from pipeline.runner_client import run_benchmark
from pipeline.state import OptimizePipelineState


async def baseline_node(state: OptimizePipelineState) -> dict:
    """Stage 3: Benchmark the original/baseline kernel."""
    run_id = state["run_id"]
    runner_url = state["runner_url"]

    status = await check_run_status(run_id)
    if status in ("cancelled",):
        return {"status": status}

    await update_run_status(run_id, "running", "baseline")
    await emit_event(run_id, "baseline", "info", "Running baseline benchmark (original code)...")

    try:
        result = await run_benchmark(runner_url, kernel="baseline", iterations=1000)
    except Exception as e:
        await emit_event(run_id, "baseline", "error", f"Baseline benchmark failed: {e}")
        return {"status": "failed", "errors": [str(e)]}

    execution = result.get("execution", {})
    power = result.get("power", {})

    await store_measurement(run_id, "baseline_total_ms", execution.get("total_ms", 0), "ms")
    await store_measurement(run_id, "baseline_per_iter_us", execution.get("per_iteration_us", 0), "us")
    if power.get("avg_power_mw"):
        await store_measurement(run_id, "baseline_power_mw", power["avg_power_mw"], "mW")
    if power.get("energy_per_iter_uj"):
        await store_measurement(run_id, "baseline_energy_uj", power["energy_per_iter_uj"], "uJ")

    await emit_event(run_id, "baseline", "success",
                     f"Baseline: {execution.get('total_ms', '?')}ms total, "
                     f"{execution.get('per_iteration_us', '?')}us/iter, "
                     f"{power.get('avg_power_mw', '?')}mW")

    return {
        "baseline_result": result,
        "current_stage": "benchmark",
    }


async def optimized_node(state: OptimizePipelineState) -> dict:
    """Stage 4: Benchmark the optimized kernel."""
    run_id = state["run_id"]
    runner_url = state["runner_url"]

    status = await check_run_status(run_id)
    if status in ("cancelled",):
        return {"status": status}

    await update_run_status(run_id, "running", "benchmark")
    await emit_event(run_id, "benchmark", "info", "Running optimized benchmark...")

    try:
        result = await run_benchmark(runner_url, kernel="optimized", iterations=1000)
    except Exception as e:
        await emit_event(run_id, "benchmark", "error", f"Optimized benchmark failed: {e}")
        return {"status": "failed", "errors": [str(e)]}

    execution = result.get("execution", {})
    power = result.get("power", {})

    await store_measurement(run_id, "optimized_total_ms", execution.get("total_ms", 0), "ms")
    await store_measurement(run_id, "optimized_per_iter_us", execution.get("per_iteration_us", 0), "us")
    if power.get("avg_power_mw"):
        await store_measurement(run_id, "optimized_power_mw", power["avg_power_mw"], "mW")
    if power.get("energy_per_iter_uj"):
        await store_measurement(run_id, "optimized_energy_uj", power["energy_per_iter_uj"], "uJ")

    await emit_event(run_id, "benchmark", "success",
                     f"Optimized: {execution.get('total_ms', '?')}ms total, "
                     f"{execution.get('per_iteration_us', '?')}us/iter, "
                     f"{power.get('avg_power_mw', '?')}mW")

    return {
        "optimized_result": result,
        "current_stage": "compare",
    }
