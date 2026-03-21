"""Debug pipeline — Stage 4: Apply fix and retest."""

from __future__ import annotations

from pipeline.callbacks import emit_event, update_run_status, check_run_status, store_measurement
from pipeline.runner_client import set_psu, run_debug, reset_dut
from pipeline.state import DebugPipelineState


async def fix_node(state: DebugPipelineState) -> dict:
    run_id = state["run_id"]
    runner_url = state["runner_url"]

    status = await check_run_status(run_id)
    if status in ("cancelled",):
        return {"status": status}

    diagnosis = state.get("diagnosis", {})
    fix = diagnosis.get("suggested_fix")

    if not fix:
        await emit_event(run_id, "fix", "info", "No fix suggested — skipping retest")
        return {
            "fix_applied": None,
            "retest_result": None,
            "comparison": None,
            "status": "completed",
            "current_stage": "complete",
        }

    await update_run_status(run_id, "running", "fix")
    await emit_event(run_id, "fix", "info", f"Applying fix: {fix.get('description', 'unknown')}")

    # Apply PSU changes if suggested
    new_voltage = fix.get("psu_voltage")
    new_current = fix.get("psu_current_limit")
    original_psu = state.get("psu_config", {"voltage": 3.3, "current_limit": 0.5})

    psu_v = new_voltage if new_voltage is not None else original_psu.get("voltage", 3.3)
    psu_i = new_current if new_current is not None else original_psu.get("current_limit", 0.5)

    try:
        await set_psu(runner_url, psu_v, psu_i, output=True)
        fix_applied = {"psu_voltage": psu_v, "psu_current_limit": psu_i}
        await emit_event(run_id, "fix", "info", f"PSU reconfigured: {psu_v}V, {psu_i}A")
    except Exception as e:
        await emit_event(run_id, "fix", "error", f"Failed to apply fix: {e}")
        return {"status": "failed", "errors": [str(e)]}

    # Retest
    await emit_event(run_id, "fix", "info", "Retesting with fix applied...")
    try:
        result = await run_debug(
            runner_url,
            psu_voltage=psu_v,
            psu_current_limit=psu_i,
            reset_before=True,
            capture_duration_ms=3000,
        )
    except Exception as e:
        await emit_event(run_id, "fix", "error", f"Retest failed: {e}")
        return {"status": "failed", "errors": [str(e)]}

    retest_scope = result.get("scope", {})
    retest_stats = retest_scope.get("stats", {})
    retest_brownout = result.get("brownout_detected", False)

    # Store retest measurements
    for name, val in retest_stats.items():
        if isinstance(val, (int, float)):
            await store_measurement(run_id, f"retest_{name}", val, "V")

    # Build comparison
    original_stats = state.get("scope_data", {}).get("stats", {})
    comparison = {
        "before": {
            "v_min": original_stats.get("v_min"),
            "v_max": original_stats.get("v_max"),
            "brownout": True,  # we're in the fix stage because original had an issue
        },
        "after": {
            "v_min": retest_stats.get("v_min"),
            "v_max": retest_stats.get("v_max"),
            "brownout": retest_brownout,
        },
        "fixed": not retest_brownout,
    }

    if retest_brownout:
        await emit_event(run_id, "fix", "warning",
                         f"Fix did NOT resolve the issue. V_min still {retest_stats.get('v_min', '?')}V")
        final_status = "failed"
    else:
        await emit_event(run_id, "fix", "success",
                         f"Fix resolved the issue! V_min now {retest_stats.get('v_min', '?')}V (was {original_stats.get('v_min', '?')}V)")
        final_status = "passed"

    return {
        "fix_applied": fix_applied,
        "retest_result": result,
        "comparison": comparison,
        "status": final_status,
        "current_stage": "complete",
    }
