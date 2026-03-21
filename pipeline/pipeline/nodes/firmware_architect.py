"""Firmware pipeline — Stage 1: Pro reads docs and produces architecture spec + subtasks."""

from __future__ import annotations

import json
import os
import re

from pipeline.callbacks import emit_event, update_run_status, check_run_status
from pipeline.state import FirmwarePipelineState

GEMINI_PRO = "gemini-3.1-pro-preview"


async def architect_node(state: FirmwarePipelineState) -> dict:
    run_id = state["run_id"]
    goal = state.get("goal", "")
    source_code = state.get("source_code", "")
    reference_docs = state.get("reference_docs", "")
    target = state.get("target", "esp32s3")
    isa_playbook = state.get("isa_playbook", "")

    status = await check_run_status(run_id)
    if status in ("cancelled",):
        return {"status": status}

    await update_run_status(run_id, "running", "architect")
    await emit_event(run_id, "architect", "info",
                     "3.1 Pro analyzing requirements, docs, and target architecture...")

    prompt = f"""You are a senior embedded systems architect. Your job is to:
1. Understand the goal and any existing code
2. Read the reference documentation and ISA capabilities
3. Produce a detailed implementation spec
4. Decompose the work into small, independent subtasks that junior engineers (smaller LLMs) can complete

## Goal
{goal}

## Target
- MCU: ESP32-S3 (Xtensa LX7 dual-core 240MHz)
- Framework: Arduino + ESP-IDF components
- Build system: PlatformIO
- Target board: esp32-s3-devkitc-1

## Existing Code (if any)
```c
{source_code[:6000] if source_code else "(no existing code — generate from scratch)"}
```

## Reference Documentation
{reference_docs[:10000] if reference_docs else "(no additional docs)"}

## ISA / Hardware Capabilities
{isa_playbook[:4000] if isa_playbook else "(use standard ESP32-S3 capabilities)"}

## Your Output

Respond in this exact JSON format:
{{
  "architecture": {{
    "description": "high-level description of what we're building",
    "modules": ["list of source files to create"],
    "dependencies": ["libraries needed, e.g. esp-dsp, ArduinoJson"],
    "memory_strategy": "where to place data (SRAM vs PSRAM), alignment requirements",
    "pin_assignments": {{"timing_gpio": 4, "other": "..."}},
    "safety_notes": ["max voltage", "watchdog", "etc"]
  }},
  "subtasks": [
    {{
      "id": "task_1",
      "file": "src/kernels.h",
      "description": "what this subtask produces",
      "spec": "detailed specification — types, function signatures, includes, constraints",
      "depends_on": [],
      "estimated_lines": 50
    }},
    {{
      "id": "task_2",
      "file": "src/kernels.cpp",
      "description": "...",
      "spec": "...",
      "depends_on": ["task_1"],
      "estimated_lines": 100
    }}
  ],
  "integration_spec": {{
    "main_cpp_structure": "how main.cpp should wire everything together",
    "command_interface": "JSON commands the firmware should accept over serial",
    "benchmark_protocol": "how timing measurement works (GPIO toggle pattern)"
  }},
  "verification_checklist": [
    "all arrays 16-byte aligned",
    "hot data in SRAM not PSRAM",
    "no division in inner loops",
    "GPIO timing uses direct register writes"
  ]
}}"""

    try:
        import google.generativeai as genai
        genai.configure(api_key=os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY", ""))
        model = genai.GenerativeModel(GEMINI_PRO)

        response = await model.generate_content_async(prompt)
        text = response.text

        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            spec = json.loads(match.group())
        else:
            await emit_event(run_id, "architect", "error", "Failed to parse architecture spec")
            return {"status": "failed", "errors": ["Pro failed to produce valid JSON spec"]}

        n_tasks = len(spec.get("subtasks", []))
        modules = spec.get("architecture", {}).get("modules", [])

        await emit_event(run_id, "architect", "success",
                         f"Architecture defined: {len(modules)} modules, {n_tasks} subtasks")

        return {
            "architecture_spec": spec.get("architecture", {}),
            "subtasks": spec.get("subtasks", []),
            "integration_spec": spec.get("integration_spec", {}),
            "verification_checklist": spec.get("verification_checklist", []),
            "current_stage": "generate",
        }

    except Exception as e:
        await emit_event(run_id, "architect", "error", f"Architect failed: {e}")
        return {"status": "failed", "errors": [str(e)]}
