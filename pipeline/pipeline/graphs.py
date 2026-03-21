"""LangGraph definitions for both pipelines."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, StateGraph

from pipeline.callbacks import emit_event, update_run_status
from pipeline.state import DebugPipelineState, FirmwarePipelineState, OptimizePipelineState

log = logging.getLogger("pipeline.graphs")


# ═══════════════════════════════════════════════════════════════════
# Debug Pipeline Graph
# ═══════════════════════════════════════════════════════════════════
#
#  [ENTRY] → setup → capture → diagnose → fix → [END]
#

async def _debug_setup(state: DebugPipelineState) -> dict:
    from pipeline.nodes.debug_setup import setup_node
    return await setup_node(state)


async def _debug_capture(state: DebugPipelineState) -> dict:
    from pipeline.nodes.debug_capture import capture_node
    return await capture_node(state)


async def _debug_diagnose(state: DebugPipelineState) -> dict:
    from pipeline.nodes.debug_diagnose import diagnose_node
    return await diagnose_node(state)


async def _debug_fix(state: DebugPipelineState) -> dict:
    from pipeline.nodes.debug_fix import fix_node
    return await fix_node(state)


def build_debug_graph():
    g = StateGraph(DebugPipelineState)
    g.add_node("setup", _debug_setup)
    g.add_node("capture", _debug_capture)
    g.add_node("diagnose", _debug_diagnose)
    g.add_node("fix", _debug_fix)

    g.set_entry_point("setup")
    g.add_edge("setup", "capture")
    g.add_edge("capture", "diagnose")
    g.add_edge("diagnose", "fix")
    g.add_edge("fix", END)

    return g.compile()


async def run_debug_pipeline(
    run_id: str,
    runner_url: str,
    goal: str = "diagnose hardware issue",
    psu_config: dict | None = None,
    dut_config: dict | None = None,
    instructions: str = "",
    callback_url: str = "",
) -> dict:
    graph = build_debug_graph()

    initial_state: dict[str, Any] = {
        "run_id": run_id,
        "runner_url": runner_url,
        "callback_url": callback_url,
        "goal": goal,
        "instructions": instructions,
        "psu_config": psu_config or {"voltage": 3.3, "current_limit": 0.5},
        "dut_config": dut_config or {},
        "scope_data": {},
        "uart_data": {},
        "psu_telemetry": {},
        "diagnosis": {},
        "fix_applied": {},
        "retest_result": {},
        "comparison": {},
        "status": "running",
        "current_stage": "setup",
        "errors": [],
    }

    try:
        result = await graph.ainvoke(initial_state)
        final_status = result.get("status", "completed")
        await update_run_status(run_id, final_status)
        return result
    except Exception as e:
        log.exception("Debug pipeline failed for run %s", run_id)
        await emit_event(run_id, "system", "error", f"Pipeline crashed: {e}")
        await update_run_status(run_id, "failed")
        return {"status": "failed", "errors": [str(e)]}


# ═══════════════════════════════════════════════════════════════════
# Optimize Pipeline Graph
# ═══════════════════════════════════════════════════════════════════
#
#  [ENTRY] → analyze → optimize → baseline → optimized → compare → [END]
#

async def _opt_analyze(state: OptimizePipelineState) -> dict:
    from pipeline.nodes.optimize_analyze import analyze_node
    return await analyze_node(state)


async def _opt_generate(state: OptimizePipelineState) -> dict:
    from pipeline.nodes.optimize_generate import optimize_node
    return await optimize_node(state)


async def _opt_baseline(state: OptimizePipelineState) -> dict:
    from pipeline.nodes.optimize_benchmark import baseline_node
    return await baseline_node(state)


async def _opt_optimized(state: OptimizePipelineState) -> dict:
    from pipeline.nodes.optimize_benchmark import optimized_node
    return await optimized_node(state)


async def _opt_compare(state: OptimizePipelineState) -> dict:
    from pipeline.nodes.optimize_compare import compare_node
    return await compare_node(state)


def build_optimize_graph():
    g = StateGraph(OptimizePipelineState)
    g.add_node("analyze", _opt_analyze)
    g.add_node("optimize", _opt_generate)
    g.add_node("baseline", _opt_baseline)
    g.add_node("optimized", _opt_optimized)
    g.add_node("compare", _opt_compare)

    g.set_entry_point("analyze")
    g.add_edge("analyze", "optimize")
    g.add_edge("optimize", "baseline")
    g.add_edge("baseline", "optimized")
    g.add_edge("optimized", "compare")
    g.add_edge("compare", END)

    return g.compile()


async def run_optimize_pipeline(
    run_id: str,
    runner_url: str,
    source_code: str,
    goal: str = "optimize for ESP32-S3",
    instructions: str = "",
    callback_url: str = "",
) -> dict:
    graph = build_optimize_graph()

    initial_state: dict[str, Any] = {
        "run_id": run_id,
        "runner_url": runner_url,
        "callback_url": callback_url,
        "goal": goal,
        "source_code": source_code,
        "instructions": instructions,
        "analysis": {},
        "optimized_code": "",
        "optimization_rationale": "",
        "isa_patterns_used": [],
        "baseline_result": {},
        "optimized_result": {},
        "comparison": {},
        "status": "running",
        "current_stage": "analyze",
        "errors": [],
    }

    try:
        result = await graph.ainvoke(initial_state)
        final_status = result.get("status", "completed")
        await update_run_status(run_id, final_status)
        return result
    except Exception as e:
        log.exception("Optimize pipeline failed for run %s", run_id)
        await emit_event(run_id, "system", "error", f"Pipeline crashed: {e}")
        await update_run_status(run_id, "failed")
        return {"status": "failed", "errors": [str(e)]}


# ═══════════════════════════════════════════════════════════════════
# Firmware Generation Pipeline Graph
# ═══════════════════════════════════════════════════════════════════
#
#  Pro reads docs     Flash Lite workers     Pro stitches        Compile loop         Flash + test
#  [ENTRY] → architect → generate → stitch → compile → flash_test → [END]
#

async def _fw_architect(state: FirmwarePipelineState) -> dict:
    from pipeline.nodes.firmware_architect import architect_node
    return await architect_node(state)


async def _fw_generate(state: FirmwarePipelineState) -> dict:
    from pipeline.nodes.firmware_generate import generate_node
    return await generate_node(state)


async def _fw_stitch(state: FirmwarePipelineState) -> dict:
    from pipeline.nodes.firmware_stitch import stitch_node
    return await stitch_node(state)


async def _fw_compile(state: FirmwarePipelineState) -> dict:
    from pipeline.nodes.firmware_compile import compile_node
    return await compile_node(state)


async def _fw_flash_test(state: FirmwarePipelineState) -> dict:
    from pipeline.nodes.firmware_flash_test import flash_test_node
    return await flash_test_node(state)


def build_firmware_graph():
    g = StateGraph(FirmwarePipelineState)
    g.add_node("architect", _fw_architect)
    g.add_node("generate", _fw_generate)
    g.add_node("stitch", _fw_stitch)
    g.add_node("compile", _fw_compile)
    g.add_node("flash_test", _fw_flash_test)

    g.set_entry_point("architect")
    g.add_edge("architect", "generate")
    g.add_edge("generate", "stitch")
    g.add_edge("stitch", "compile")
    g.add_edge("compile", "flash_test")
    g.add_edge("flash_test", END)

    return g.compile()


async def run_firmware_pipeline(
    run_id: str,
    runner_url: str,
    goal: str,
    source_code: str = "",
    reference_docs: str = "",
    isa_playbook: str = "",
    target: str = "esp32s3",
    project_path: str = "/home/pi/benchagent/firmware/generated",
    instructions: str = "",
    callback_url: str = "",
) -> dict:
    graph = build_firmware_graph()

    initial_state: dict[str, Any] = {
        "run_id": run_id,
        "runner_url": runner_url,
        "callback_url": callback_url,
        "goal": goal,
        "source_code": source_code,
        "reference_docs": reference_docs,
        "isa_playbook": isa_playbook,
        "target": target,
        "project_path": project_path,
        "instructions": instructions,
        "architecture_spec": {},
        "subtasks": [],
        "integration_spec": {},
        "verification_checklist": [],
        "generated_files": {},
        "final_files": {},
        "review_notes": [],
        "verification_result": {},
        "compiled_files": {},
        "compile_result": {},
        "compile_attempts": 0,
        "test_results": {},
        "status": "running",
        "current_stage": "architect",
        "errors": [],
    }

    try:
        result = await graph.ainvoke(initial_state)
        final_status = result.get("status", "completed")
        await update_run_status(run_id, final_status)
        return result
    except Exception as e:
        log.exception("Firmware pipeline failed for run %s", run_id)
        await emit_event(run_id, "system", "error", f"Pipeline crashed: {e}")
        await update_run_status(run_id, "failed")
        return {"status": "failed", "errors": [str(e)]}
