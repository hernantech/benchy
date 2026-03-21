"""Firmware pipeline — Stage 5: Flash to ESP32 and run verification test."""

from __future__ import annotations

from pipeline.callbacks import emit_event, update_run_status, check_run_status, store_measurement
from pipeline.runner_client import call_runner, esp_command, run_benchmark
from pipeline.state import FirmwarePipelineState


async def flash_test_node(state: FirmwarePipelineState) -> dict:
    run_id = state["run_id"]
    runner_url = state["runner_url"]
    project_path = state.get("project_path", "/home/pi/benchagent/firmware/generated")
    target = state.get("target", "esp32s3")

    status = await check_run_status(run_id)
    if status in ("cancelled",):
        return {"status": status}

    await update_run_status(run_id, "running", "flash")
    await emit_event(run_id, "flash", "info", "Flashing firmware to ESP32-S3...")

    # Flash
    try:
        flash_result = await call_runner(runner_url, "/esp32/a/flash", {
            "project_path": project_path,
            "target": target,
        }, timeout=300)

        if not flash_result.get("ok"):
            await emit_event(run_id, "flash", "error", "Flash failed")
            return {"status": "failed", "errors": ["Flash failed"]}

        await emit_event(run_id, "flash", "success",
                         f"Flashed in {flash_result.get('build_time_s', '?')}s")
    except Exception as e:
        await emit_event(run_id, "flash", "error", f"Flash error: {e}")
        return {"status": "failed", "errors": [str(e)]}

    # Verify: send status command, check board responds
    await emit_event(run_id, "flash", "info", "Verifying firmware responds...")
    try:
        status_resp = await esp_command(runner_url, "a", {"cmd": "status"})
        resp = status_resp.get("response", {})
        if isinstance(resp, dict) and resp.get("ok"):
            await emit_event(run_id, "flash", "success",
                             f"Firmware alive: {resp.get('free_heap', '?')} bytes free heap")
        else:
            await emit_event(run_id, "flash", "warning", f"Unexpected status response: {resp}")
    except Exception as e:
        await emit_event(run_id, "flash", "warning", f"Status check failed: {e}")

    # Run benchmarks if the firmware supports them
    test_results = {}
    for kernel_name in ("baseline", "optimized"):
        try:
            await emit_event(run_id, "flash", "info", f"Running benchmark: {kernel_name}...")
            result = await run_benchmark(runner_url, kernel=kernel_name, iterations=1000)

            execution = result.get("execution", {})
            power = result.get("power", {})

            test_results[kernel_name] = result

            total_ms = execution.get("total_ms", 0)
            per_us = execution.get("per_iteration_us", 0)
            power_mw = power.get("avg_power_mw", 0)

            await store_measurement(run_id, f"{kernel_name}_total_ms", total_ms, "ms")
            await store_measurement(run_id, f"{kernel_name}_per_iter_us", per_us, "us")
            if power_mw:
                await store_measurement(run_id, f"{kernel_name}_power_mw", power_mw, "mW")

            await emit_event(run_id, "flash", "success",
                             f"{kernel_name}: {total_ms:.1f}ms total, {per_us:.1f}us/iter, {power_mw:.0f}mW")
        except Exception as e:
            await emit_event(run_id, "flash", "warning",
                             f"Benchmark '{kernel_name}' not available: {e}")

    # Compute speedup if both ran
    if "baseline" in test_results and "optimized" in test_results:
        b_us = test_results["baseline"].get("execution", {}).get("per_iteration_us", 0)
        o_us = test_results["optimized"].get("execution", {}).get("per_iteration_us", 0)
        speedup = b_us / o_us if o_us > 0 else 0
        await store_measurement(run_id, "speedup_x", speedup, "x")
        await emit_event(run_id, "flash", "success", f"Speedup: {speedup:.1f}x")

    return {
        "test_results": test_results,
        "status": "passed" if test_results else "completed",
        "current_stage": "complete",
    }
