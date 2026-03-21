"""Firmware pipeline — Stage 2: Flash Lite workers generate code from subtask specs."""

from __future__ import annotations

import asyncio
import json
import os
import re

from pipeline.callbacks import emit_event, update_run_status, check_run_status
from pipeline.state import FirmwarePipelineState

GEMINI_FLASH_LITE = "gemini-3.1-flash-lite-preview"  # cheap, fast workers
MAX_CONCURRENT = 3


async def _generate_subtask(
    run_id: str,
    subtask: dict,
    completed_files: dict[str, str],
    target: str,
) -> tuple[str, str]:
    """Generate one file from a subtask spec using Flash Lite. Returns (filename, code)."""
    import google.generativeai as genai
    genai.configure(api_key=os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY", ""))
    model = genai.GenerativeModel(GEMINI_FLASH_LITE)

    task_id = subtask.get("id", "unknown")
    filename = subtask.get("file", "unknown.cpp")
    spec = subtask.get("spec", "")
    description = subtask.get("description", "")
    depends_on = subtask.get("depends_on", [])

    # Include dependency files for context
    dep_context = ""
    for dep_id in depends_on:
        for dep_file, dep_code in completed_files.items():
            if dep_id in dep_file or dep_file in str(subtask):
                dep_context += f"\n// === {dep_file} ===\n{dep_code}\n"

    prompt = f"""You are a firmware engineer. Generate ONLY the code for this file. No explanations.

## Target
ESP32-S3, Arduino + ESP-IDF, PlatformIO

## Task: {description}
## File: {filename}

## Specification
{spec}

## Dependencies (already written)
{dep_context[:4000] if dep_context else "(no dependencies)"}

## Rules
- Include all necessary #include directives
- Use exact types and signatures from the spec
- ESP32-S3 specific: use `esp_timer_get_time()` for microsecond timing
- For GPIO timing: use `GPIO.out_w1ts` / `GPIO.out_w1tc` (direct register, not digitalWrite)
- 16-byte align arrays: `__attribute__((aligned(16)))`
- SRAM placement: `__attribute__((section(".dram1")))`
- Must compile for target `{target}`

Output ONLY the file contents. Start with the first #include. No markdown fences, no explanations."""

    try:
        response = await model.generate_content_async(prompt)
        code = response.text.strip()

        # Strip markdown fences if model added them anyway
        if code.startswith("```"):
            code = re.sub(r"^```(?:c|cpp|h)?\s*\n?", "", code)
            code = re.sub(r"\n?```\s*$", "", code)

        await emit_event(run_id, "generate", "info",
                         f"[Flash Lite] Generated {filename} ({len(code.splitlines())} lines)")
        return filename, code

    except Exception as e:
        await emit_event(run_id, "generate", "warning", f"[Flash Lite] Failed {filename}: {e}")
        return filename, f"// GENERATION FAILED: {e}\n"


async def generate_node(state: FirmwarePipelineState) -> dict:
    run_id = state["run_id"]
    subtasks = state.get("subtasks", [])
    target = state.get("target", "esp32s3")

    status = await check_run_status(run_id)
    if status in ("cancelled",):
        return {"status": status}

    await update_run_status(run_id, "running", "generate")
    await emit_event(run_id, "generate", "info",
                     f"Dispatching {len(subtasks)} subtasks to Flash Lite workers...")

    # Topological sort: process tasks respecting depends_on
    completed_files: dict[str, str] = {}
    remaining = list(subtasks)
    generated_files: dict[str, str] = {}

    max_rounds = 10
    for round_num in range(max_rounds):
        if not remaining:
            break

        # Find tasks whose dependencies are satisfied
        ready = []
        still_waiting = []
        for task in remaining:
            deps = task.get("depends_on", [])
            if all(any(d in f for f in completed_files) for d in deps) or not deps:
                ready.append(task)
            else:
                still_waiting.append(task)

        if not ready:
            # Deadlock — force remaining tasks
            await emit_event(run_id, "generate", "warning",
                             f"Dependency deadlock on round {round_num+1}, forcing {len(still_waiting)} tasks")
            ready = still_waiting
            still_waiting = []

        # Run ready tasks concurrently (bounded)
        sem = asyncio.Semaphore(MAX_CONCURRENT)

        async def _bounded(task):
            async with sem:
                return await _generate_subtask(run_id, task, completed_files, target)

        results = await asyncio.gather(*[_bounded(t) for t in ready], return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                await emit_event(run_id, "generate", "warning", f"Subtask failed: {result}")
                continue
            filename, code = result
            completed_files[filename] = code
            generated_files[filename] = code

        remaining = still_waiting

    await emit_event(run_id, "generate", "success",
                     f"Generated {len(generated_files)} files across {round_num+1} rounds")

    return {
        "generated_files": generated_files,
        "current_stage": "stitch",
    }
