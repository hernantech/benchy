"""HTTP client for the RPi hardware runner (Pi worker)."""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger("pipeline.runner")

DEFAULT_TIMEOUT = 30.0  # scope captures can take a few seconds


async def call_runner(
    runner_url: str,
    endpoint: str,
    body: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    """Call a Pi worker endpoint. Returns parsed JSON response."""
    url = f"{runner_url}{endpoint}"
    async with httpx.AsyncClient() as client:
        if body is not None:
            resp = await client.post(url, json=body, timeout=timeout)
        else:
            resp = await client.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()


# ── Convenience wrappers ──────────────────────────────────────────

async def set_psu(runner_url: str, voltage: float, current_limit: float, output: bool = True) -> dict:
    return await call_runner(runner_url, "/psu/configure", {
        "voltage": voltage, "current_limit": current_limit, "output": output,
    })


async def psu_off(runner_url: str) -> dict:
    return await call_runner(runner_url, "/psu/off")


async def psu_state(runner_url: str) -> dict:
    return await call_runner(runner_url, "/psu/state")


async def sweep_voltage(runner_url: str, start: float, stop: float, step: float, dwell: float = 0.5) -> dict:
    return await call_runner(runner_url, "/psu/sweep", {
        "start": start, "stop": stop, "step": step, "dwell": dwell,
    })


async def scope_capture(runner_url: str, channel: int = 0, **kwargs) -> dict:
    return await call_runner(runner_url, "/scope/capture", {"channel": channel, **kwargs})


async def scope_pulse_width(runner_url: str, channel: int = 0, trigger_level: float = 1.5) -> dict:
    return await call_runner(runner_url, "/scope/pulse_width", {
        "channel": channel, "trigger_level": trigger_level,
    })


async def run_debug(runner_url: str, **kwargs) -> dict:
    return await call_runner(runner_url, "/run/debug", kwargs, timeout=60.0)


async def run_benchmark(runner_url: str, kernel: str, iterations: int = 1000, **kwargs) -> dict:
    return await call_runner(runner_url, "/run/benchmark", {
        "kernel": kernel, "iterations": iterations, **kwargs,
    }, timeout=60.0)


async def esp_command(runner_url: str, board: str, cmd: dict, timeout_ms: int = 5000) -> dict:
    import json
    return await call_runner(runner_url, f"/esp32/{board}/serial/send", {
        "command": json.dumps(cmd), "timeout_ms": timeout_ms,
    })


async def reset_dut(runner_url: str) -> dict:
    return await call_runner(runner_url, "/esp32/a/reset")
