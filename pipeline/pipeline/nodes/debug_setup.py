"""Debug pipeline — Stage 1: Setup instruments and DUT."""

from __future__ import annotations

from pipeline.callbacks import emit_event, update_run_status, check_run_status
from pipeline.runner_client import set_psu, esp_command, reset_dut
from pipeline.state import DebugPipelineState


async def setup_node(state: DebugPipelineState) -> dict:
    run_id = state["run_id"]
    runner_url = state["runner_url"]

    status = await check_run_status(run_id)
    if status in ("cancelled",):
        return {"status": status}

    await update_run_status(run_id, "running", "setup")
    await emit_event(run_id, "setup", "info", "Configuring instruments...")

    psu_config = state.get("psu_config", {"voltage": 3.3, "current_limit": 0.5})
    try:
        await set_psu(runner_url, **psu_config)
        await emit_event(run_id, "setup", "success",
                         f"PSU set to {psu_config.get('voltage', 3.3)}V, {psu_config.get('current_limit', 0.5)}A")
    except Exception as e:
        await emit_event(run_id, "setup", "error", f"PSU configuration failed: {e}")
        return {"status": "failed", "errors": [str(e)]}

    # Send any DUT setup commands (e.g., wifi_connect, i2c_init)
    dut_config = state.get("dut_config", {})
    if dut_config:
        try:
            result = await esp_command(runner_url, "a", dut_config)
            await emit_event(run_id, "setup", "info", f"DUT configured: {dut_config.get('cmd', 'unknown')}")
        except Exception as e:
            await emit_event(run_id, "setup", "warning", f"DUT config failed (continuing): {e}")

    # Reset DUT to start fresh
    try:
        await reset_dut(runner_url)
        await emit_event(run_id, "setup", "info", "DUT reset")
    except Exception as e:
        await emit_event(run_id, "setup", "warning", f"DUT reset failed: {e}")

    return {"current_stage": "capture"}
