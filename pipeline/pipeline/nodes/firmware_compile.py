"""Firmware pipeline — Stage 4: Write files to disk, compile, handle errors with Flash Lite fixes."""

from __future__ import annotations

import json
import os
import re

from pipeline.callbacks import emit_event, update_run_status, check_run_status
from pipeline.runner_client import call_runner
from pipeline.state import FirmwarePipelineState

GEMINI_PRO = "gemini-3.1-pro-preview"      # diagnose compile errors
GEMINI_FLASH_LITE = "gemini-3.1-flash-lite-preview"  # quick fixes
MAX_FIX_ATTEMPTS = 3


async def _write_files_to_runner(runner_url: str, project_path: str, files: dict[str, str]) -> None:
    """Write firmware files to the Pi via the runner API."""
    # The runner needs an endpoint for this, or we write via SSH/SFTP
    # For hackathon simplicity: POST the files as a bundle
    await call_runner(runner_url, "/firmware/write", {
        "project_path": project_path,
        "files": files,
    }, timeout=10)


async def _compile_on_runner(runner_url: str, project_path: str, target: str) -> dict:
    """Trigger PlatformIO build on the Pi runner. Returns {ok, output, errors}."""
    return await call_runner(runner_url, "/firmware/compile", {
        "project_path": project_path,
        "target": target,
    }, timeout=120)


async def _fix_compile_error(
    run_id: str,
    error_output: str,
    files: dict[str, str],
    attempt: int,
) -> dict[str, str]:
    """Use Pro to diagnose, Flash Lite to fix."""
    import google.generativeai as genai
    genai.configure(api_key=os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY", ""))

    # Pro diagnoses
    await emit_event(run_id, "compile", "info",
                     f"[attempt {attempt}] Pro diagnosing compile error...")

    pro = genai.GenerativeModel(GEMINI_PRO)

    files_text = ""
    for fname, code in files.items():
        lines = code.split("\n")
        numbered = "\n".join(f"{i+1:4d} | {line}" for i, line in enumerate(lines))
        files_text += f"\n// ═══ {fname} ═══\n{numbered}\n"

    diag_prompt = f"""A firmware build for ESP32-S3 (PlatformIO, Arduino framework) failed.

## Compiler Output
```
{error_output[-3000:]}
```

## Source Files
{files_text[:10000]}

Identify the exact errors and for each one specify:
1. Which file and line
2. What's wrong
3. The exact fix (show the corrected line)

Respond as JSON:
{{
  "errors": [
    {{"file": "src/main.cpp", "line": 42, "issue": "...", "fix": "corrected line content"}}
  ]
}}"""

    diag_response = await pro.generate_content_async(diag_prompt)
    diag_text = diag_response.text

    match = re.search(r"\{[\s\S]*\}", diag_text)
    if not match:
        return files  # can't parse, return unchanged

    diagnosis = json.loads(match.group())
    errors = diagnosis.get("errors", [])

    if not errors:
        return files

    # Flash Lite applies fixes
    await emit_event(run_id, "compile", "info",
                     f"[attempt {attempt}] Flash Lite applying {len(errors)} fixes...")

    lite = genai.GenerativeModel(GEMINI_FLASH_LITE)
    fixed_files = dict(files)

    for err in errors:
        fname = err.get("file", "")
        if fname not in fixed_files:
            continue

        fix_prompt = f"""Fix this compile error in {fname} for ESP32-S3.

Error: {err.get('issue', 'unknown')}
Line {err.get('line', '?')}: needs to be changed to: {err.get('fix', '')}

Current file:
```
{fixed_files[fname]}
```

Output ONLY the complete corrected file. No explanations. No markdown fences."""

        try:
            fix_response = await lite.generate_content_async(fix_prompt)
            fixed_code = fix_response.text.strip()
            if fixed_code.startswith("```"):
                fixed_code = re.sub(r"^```(?:c|cpp|h)?\s*\n?", "", fixed_code)
                fixed_code = re.sub(r"\n?```\s*$", "", fixed_code)
            if len(fixed_code) > 10:  # sanity check
                fixed_files[fname] = fixed_code
        except Exception:
            pass  # skip this fix, try compiling anyway

    return fixed_files


async def compile_node(state: FirmwarePipelineState) -> dict:
    run_id = state["run_id"]
    runner_url = state["runner_url"]
    final_files = state.get("final_files", {})
    target = state.get("target", "esp32s3")
    project_path = state.get("project_path", "/home/pi/benchagent/firmware/generated")

    status = await check_run_status(run_id)
    if status in ("cancelled",):
        return {"status": status}

    await update_run_status(run_id, "running", "compile")

    current_files = dict(final_files)

    for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
        await emit_event(run_id, "compile", "info",
                         f"Compile attempt {attempt}/{MAX_FIX_ATTEMPTS}...")

        try:
            # Write files to Pi
            await _write_files_to_runner(runner_url, project_path, current_files)

            # Compile
            result = await _compile_on_runner(runner_url, project_path, target)

            if result.get("ok"):
                await emit_event(run_id, "compile", "success",
                                 f"Build succeeded on attempt {attempt}! "
                                 f"Binary size: {result.get('size_bytes', '?')} bytes")
                return {
                    "compiled_files": current_files,
                    "compile_result": result,
                    "compile_attempts": attempt,
                    "current_stage": "flash",
                }

            # Compile failed — try to fix
            error_output = result.get("output", "") + result.get("errors", "")
            await emit_event(run_id, "compile", "warning",
                             f"Build failed (attempt {attempt}). Analyzing errors...")

            if attempt < MAX_FIX_ATTEMPTS:
                current_files = await _fix_compile_error(
                    run_id, error_output, current_files, attempt
                )
            else:
                await emit_event(run_id, "compile", "error",
                                 f"Build failed after {MAX_FIX_ATTEMPTS} attempts")
                return {
                    "compiled_files": current_files,
                    "compile_result": result,
                    "compile_attempts": attempt,
                    "status": "failed",
                    "errors": [f"Compile failed after {MAX_FIX_ATTEMPTS} attempts"],
                }

        except Exception as e:
            await emit_event(run_id, "compile", "error", f"Compile step error: {e}")
            if attempt == MAX_FIX_ATTEMPTS:
                return {"status": "failed", "errors": [str(e)]}

    return {"status": "failed", "errors": ["Exhausted compile attempts"]}
