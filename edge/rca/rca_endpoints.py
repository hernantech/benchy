"""
FastAPI endpoints for the RCA module — to be integrated into the edge worker.

These endpoints expose the RCA pipeline as HTTP tools that the Gemini chat
agent calls via the frontend. The Gemini agent is the Tier 3 decision maker;
these endpoints provide the Tier 1 + Tier 2 analysis.

Integration: import and mount in worker.py:
    from rca.rca_endpoints import rca_router
    app.include_router(rca_router, prefix="/rca")
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter

from .orchestrator import RCAPipeline, RCASession
from .signal_processing import ThresholdSpec

rca_router = APIRouter(tags=["rca"])

# In-memory session store (sufficient for single-RPi deployment)
_sessions: dict[str, RCASession] = {}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class RCACreateReq(BaseModel):
    test_goal: str = Field(description="What is being tested (e.g., '3.3V rail stability')")
    test_point: str = Field(description="Physical test point (e.g., 'U3 output pin 5')")
    board: str = Field(default="ESP32-S3-DevKitC-1")
    max_iterations: int = Field(default=5, ge=1, le=10)


class RCAAnalyzeReq(BaseModel):
    session_id: str
    # Waveform data (from /scope/capture)
    waveform_data: Optional[list[float]] = None
    sample_rate: float = 1_000_000
    # Threshold spec
    expected_voltage: Optional[float] = None
    voltage_tolerance_pct: float = 5.0
    max_ripple_mv: Optional[float] = None
    max_rise_time_ns: Optional[float] = None
    max_overshoot_pct: float = 10.0
    # PSU telemetry (from /psu/state)
    psu_voltage: Optional[float] = None
    psu_current: Optional[float] = None
    # CAN bus data (dual-channel scope capture)
    can_h_data: Optional[list[float]] = None
    can_l_data: Optional[list[float]] = None
    # Serial log (from /esp32/{board}/serial/read)
    serial_log: Optional[str] = None
    # Firmware source (for firmware-related hypotheses)
    firmware_source: Optional[str] = None


class RCAReportReq(BaseModel):
    session_id: str
    reason: str = Field(default="resolved", description="Resolution reason")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@rca_router.post("/session")
async def create_rca_session(req: RCACreateReq):
    """Create a new RCA session. Returns session ID for subsequent analyze calls."""
    session = RCAPipeline.create_session(
        test_goal=req.test_goal,
        test_point=req.test_point,
        board=req.board,
        max_iterations=req.max_iterations,
    )
    _sessions[session.session_id] = session
    return {
        "session_id": session.session_id,
        "session": session.to_dict(),
    }


@rca_router.post("/analyze")
async def analyze_rca(req: RCAAnalyzeReq):
    """
    Run one iteration of Tier 1 + Tier 2 analysis.
    Feed it scope data, PSU telemetry, and/or serial logs.
    Returns structured metrics + ranked hypotheses for the Gemini agent.
    """
    session = _sessions.get(req.session_id)
    if not session:
        return {"error": f"Session {req.session_id} not found"}

    # Build threshold spec from request
    spec = ThresholdSpec(
        dc_voltage=req.expected_voltage,
        dc_tolerance_pct=req.voltage_tolerance_pct,
        max_ripple_mv=req.max_ripple_mv,
        max_rise_time_ns=req.max_rise_time_ns,
        max_overshoot_pct=req.max_overshoot_pct,
    )

    result = RCAPipeline.run_analysis(
        session,
        waveform_samples=req.waveform_data,
        sample_rate=req.sample_rate,
        spec=spec,
        psu_voltage=req.psu_voltage,
        psu_current=req.psu_current,
        serial_log=req.serial_log,
        firmware_source=req.firmware_source,
        can_h_samples=req.can_h_data,
        can_l_samples=req.can_l_data,
    )

    return result


@rca_router.post("/report")
async def generate_rca_report(req: RCAReportReq):
    """Generate the final RCA report for a session."""
    session = _sessions.get(req.session_id)
    if not session:
        return {"error": f"Session {req.session_id} not found"}

    return RCAPipeline.generate_report(session, req.reason)


@rca_router.get("/session/{session_id}")
async def get_rca_session(session_id: str):
    """Get current state of an RCA session."""
    session = _sessions.get(session_id)
    if not session:
        return {"error": f"Session {session_id} not found"}

    return {
        "session": session.to_dict(),
        "iteration_count": session.current_iteration,
        "has_report": session.final_report is not None,
    }


@rca_router.get("/sessions")
async def list_rca_sessions():
    """List all active RCA sessions."""
    return {
        "sessions": [s.to_dict() for s in _sessions.values()],
    }
