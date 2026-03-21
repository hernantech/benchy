"""BenchAgent Pipeline Service — FastAPI entry point.

Two pipelines:
  POST /debug    — hardware debug (setup → capture → diagnose → fix)
  POST /optimize — ISA optimization (analyze → optimize → baseline → benchmark → compare)

Both run as background tasks and push events to Supabase.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel

from pipeline.callbacks import SUPABASE_URL, _HEADERS
from pipeline.graphs import run_debug_pipeline, run_firmware_pipeline, run_optimize_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("pipeline")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Pipeline service starting")
    yield
    log.info("Pipeline service stopping")


app = FastAPI(title="BenchAgent Pipeline", lifespan=lifespan)


# ── Request Models ───────────────────────────────────────────────

class DebugRequest(BaseModel):
    run_id: str | None = None
    runner_url: str = "http://benchagent-pi:8420"
    goal: str = "diagnose hardware issue"
    psu_voltage: float = 3.3
    psu_current_limit: float = 0.5
    dut_command: dict | None = None
    instructions: str = ""


class FirmwareRequest(BaseModel):
    run_id: str | None = None
    runner_url: str = "http://benchagent-pi:8420"
    goal: str
    source_code: str = ""
    reference_docs: str = ""
    isa_playbook: str = ""
    target: str = "esp32s3"
    project_path: str = "/home/pi/benchagent/firmware/generated"
    instructions: str = ""


class OptimizeRequest(BaseModel):
    run_id: str | None = None
    runner_url: str = "http://benchagent-pi:8420"
    source_code: str
    goal: str = "optimize for ESP32-S3"
    instructions: str = ""


# ── Helpers ──────────────────────────────────────────────────────

async def _create_run(goal: str, trigger_type: str = "pipeline") -> str:
    """Create a run row in Supabase, return the run_id."""
    run_id = str(uuid.uuid4())
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{SUPABASE_URL}/rest/v1/runs",
                headers=_HEADERS,
                json={
                    "id": run_id,
                    "status": "queued",
                    "goal": goal,
                    "trigger_type": trigger_type,
                },
                timeout=5,
            )
    except Exception as e:
        log.warning("Failed to create run row: %s", e)
    return run_id


# ── Routes ───────────────────────────────────────────────────────

@app.post("/debug")
async def start_debug(req: DebugRequest, bg: BackgroundTasks):
    run_id = req.run_id or await _create_run(req.goal, "debug")

    bg.add_task(
        run_debug_pipeline,
        run_id=run_id,
        runner_url=req.runner_url,
        goal=req.goal,
        psu_config={"voltage": req.psu_voltage, "current_limit": req.psu_current_limit},
        dut_config=req.dut_command,
        instructions=req.instructions,
    )

    return {"status": "started", "run_id": run_id}


@app.post("/firmware")
async def start_firmware(req: FirmwareRequest, bg: BackgroundTasks):
    run_id = req.run_id or await _create_run(req.goal, "firmware")

    bg.add_task(
        run_firmware_pipeline,
        run_id=run_id,
        runner_url=req.runner_url,
        goal=req.goal,
        source_code=req.source_code,
        reference_docs=req.reference_docs,
        isa_playbook=req.isa_playbook,
        target=req.target,
        project_path=req.project_path,
        instructions=req.instructions,
    )

    return {"status": "started", "run_id": run_id}


@app.post("/optimize")
async def start_optimize(req: OptimizeRequest, bg: BackgroundTasks):
    run_id = req.run_id or await _create_run(req.goal, "optimize")

    bg.add_task(
        run_optimize_pipeline,
        run_id=run_id,
        runner_url=req.runner_url,
        source_code=req.source_code,
        goal=req.goal,
        instructions=req.instructions,
    )

    return {"status": "started", "run_id": run_id}


@app.get("/health")
async def health():
    return {"status": "ok", "pipelines": ["debug", "firmware", "optimize"]}
