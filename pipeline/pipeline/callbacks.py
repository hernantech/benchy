"""Event emission and status updates — posts to Supabase via REST API."""

from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger("pipeline.callbacks")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}


async def emit_event(
    run_id: str,
    stage: str,
    event_type: str,
    message: str,
    metadata: dict | None = None,
) -> None:
    """Insert a run_steps row (acts as the event log)."""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{SUPABASE_URL}/rest/v1/run_steps",
                headers=_HEADERS,
                json={
                    "run_id": run_id,
                    "seq": 0,  # will be overwritten by trigger or ignored
                    "command_type": stage,
                    "status": event_type,  # info|success|warning|error
                    "result": {"message": message, **(metadata or {})},
                },
                timeout=5,
            )
    except Exception as e:
        log.warning("Failed to emit event for %s: %s", run_id, e)


async def update_run_status(
    run_id: str,
    status: str,
    stage: str | None = None,
) -> None:
    """Update the runs table status."""
    try:
        body: dict = {"status": status}
        if stage:
            body["agent_plan"] = {"current_stage": stage}
        if status == "running" and stage:
            body["started_at"] = "now()"
        if status in ("completed", "failed", "error"):
            body["finished_at"] = "now()"

        async with httpx.AsyncClient() as client:
            await client.patch(
                f"{SUPABASE_URL}/rest/v1/runs?id=eq.{run_id}",
                headers=_HEADERS,
                json=body,
                timeout=5,
            )
    except Exception as e:
        log.warning("Failed to update status for %s: %s", run_id, e)


async def store_measurement(
    run_id: str,
    name: str,
    value: float,
    unit: str,
    tags: dict | None = None,
) -> None:
    """Insert a measurement row."""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{SUPABASE_URL}/rest/v1/measurements",
                headers=_HEADERS,
                json={
                    "run_id": run_id,
                    "name": name,
                    "value": value,
                    "unit": unit,
                    "tags": tags or {},
                },
                timeout=5,
            )
    except Exception as e:
        log.warning("Failed to store measurement for %s: %s", run_id, e)


async def store_diagnosis(
    run_id: str,
    model: str,
    summary: str,
    root_cause: str | None = None,
    confidence: float | None = None,
    suggested_fix: dict | None = None,
) -> None:
    """Insert a diagnosis row."""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{SUPABASE_URL}/rest/v1/diagnoses",
                headers=_HEADERS,
                json={
                    "run_id": run_id,
                    "model": model,
                    "summary": summary,
                    "root_cause": root_cause,
                    "confidence": confidence,
                    "suggested_fix": suggested_fix,
                },
                timeout=5,
            )
    except Exception as e:
        log.warning("Failed to store diagnosis for %s: %s", run_id, e)


async def check_run_status(run_id: str) -> str:
    """Check if the run has been cancelled/paused."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/runs?id=eq.{run_id}&select=status",
                headers=_HEADERS,
                timeout=5,
            )
            rows = resp.json()
            if rows:
                return rows[0].get("status", "running")
    except Exception:
        pass
    return "running"
