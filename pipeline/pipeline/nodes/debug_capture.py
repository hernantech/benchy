"""Debug pipeline — Stage 2: Capture scope + UART + PSU telemetry."""

from __future__ import annotations

from pipeline.callbacks import emit_event, update_run_status, check_run_status, store_measurement
from pipeline.runner_client import run_debug, psu_state
from pipeline.state import DebugPipelineState


async def capture_node(state: DebugPipelineState) -> dict:
    run_id = state["run_id"]
    runner_url = state["runner_url"]

    status = await check_run_status(run_id)
    if status in ("cancelled",):
        return {"status": status}

    await update_run_status(run_id, "running", "capture")
    await emit_event(run_id, "capture", "info", "Capturing scope + UART + PSU data...")

    psu_config = state.get("psu_config", {"voltage": 3.3, "current_limit": 0.5})

    try:
        result = await run_debug(
            runner_url,
            psu_voltage=psu_config.get("voltage", 3.3),
            psu_current_limit=psu_config.get("current_limit", 0.5),
            reset_before=True,
            capture_duration_ms=3000,
        )
    except Exception as e:
        await emit_event(run_id, "capture", "error", f"Capture failed: {e}")
        return {"status": "failed", "errors": [str(e)]}

    scope = result.get("scope", {})
    uart = result.get("uart", {})
    psu = result.get("psu", {})
    brownout = result.get("brownout_detected", False)

    stats = scope.get("stats", {})

    # Store key measurements
    for name, val in stats.items():
        if isinstance(val, (int, float)):
            await store_measurement(run_id, name, val, "V")

    if psu.get("output_current"):
        await store_measurement(run_id, "psu_current", psu["output_current"], "A")
    if psu.get("output_power"):
        await store_measurement(run_id, "psu_power", psu["output_power"], "W")

    if brownout:
        await emit_event(run_id, "capture", "warning",
                         f"Brownout detected! V_min={stats.get('v_min', '?')}V")
    else:
        await emit_event(run_id, "capture", "success",
                         f"Capture complete. V_min={stats.get('v_min', '?')}V, "
                         f"V_max={stats.get('v_max', '?')}V")

    uart_text = uart.get("data", "")
    if uart_text:
        # Truncate for log
        preview = uart_text[:200] + ("..." if len(uart_text) > 200 else "")
        await emit_event(run_id, "capture", "info", f"UART: {preview}")

    return {
        "scope_data": scope,
        "uart_data": uart,
        "psu_telemetry": psu,
        "current_stage": "diagnose",
    }
