"""Firmware pipeline — Stage 3: Pro stitches files together, writes main.cpp, verifies."""

from __future__ import annotations

import json
import os
import re

from pipeline.callbacks import emit_event, update_run_status, check_run_status
from pipeline.state import FirmwarePipelineState

GEMINI_PRO = "gemini-3.1-pro-preview"


async def stitch_node(state: FirmwarePipelineState) -> dict:
    run_id = state["run_id"]
    generated_files = state.get("generated_files", {})
    integration_spec = state.get("integration_spec", {})
    architecture_spec = state.get("architecture_spec", {})
    verification_checklist = state.get("verification_checklist", [])

    status = await check_run_status(run_id)
    if status in ("cancelled",):
        return {"status": status}

    await update_run_status(run_id, "running", "stitch")
    await emit_event(run_id, "stitch", "info",
                     "3.1 Pro stitching files, writing main.cpp, verifying correctness...")

    # Build the full file listing for Pro to review
    files_text = ""
    for fname, code in generated_files.items():
        files_text += f"\n// ═══ {fname} ═══\n{code}\n"

    prompt = f"""You are a senior firmware engineer doing final integration and verification.

## Architecture
{json.dumps(architecture_spec, indent=2)[:3000]}

## Integration Specification
{json.dumps(integration_spec, indent=2)[:2000]}

## Generated Files (by junior engineers)
{files_text[:12000]}

## Verification Checklist
{json.dumps(verification_checklist, indent=2)}

## Your Tasks

1. **Review** each generated file for correctness:
   - Type mismatches, missing includes, wrong function signatures
   - ESP32-S3 compatibility issues
   - Memory alignment violations (arrays must be 16-byte aligned for SIMD)
   - PSRAM vs SRAM placement errors

2. **Write main.cpp** that ties everything together:
   - JSON command interface over USB Serial (matching the DUT firmware pattern)
   - Benchmark harness with GPIO timing (direct register writes)
   - Must respond to {{"cmd":"benchmark","kernel":"baseline","iterations":1000}}
   - Must respond to {{"cmd":"benchmark","kernel":"optimized","iterations":1000}}
   - Must respond to {{"cmd":"status"}} with {{"board":"dut",...}}

3. **Fix** any issues found in the generated files

4. **Write platformio.ini** for ESP32-S3 DevKitC-1

Respond in this exact JSON format:
{{
  "review_notes": [
    {{"file": "filename", "issue": "what's wrong", "fix": "what you changed"}}
  ],
  "files": {{
    "src/main.cpp": "// full file contents...",
    "platformio.ini": "full contents...",
    "src/other_file.h": "corrected contents if needed..."
  }},
  "verification_result": {{
    "all_checks_passed": true,
    "issues_found": 0,
    "issues_fixed": 0,
    "notes": "any remaining concerns"
  }}
}}

IMPORTANT: The "files" dict must contain COMPLETE file contents, not diffs. Include ALL generated files (corrected if needed) plus main.cpp and platformio.ini."""

    try:
        import google.generativeai as genai
        genai.configure(api_key=os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY", ""))
        model = genai.GenerativeModel(GEMINI_PRO)

        response = await model.generate_content_async(prompt)
        text = response.text

        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            result = json.loads(match.group())
        else:
            await emit_event(run_id, "stitch", "error", "Pro failed to produce valid JSON")
            return {"status": "failed", "errors": ["Stitch produced invalid output"]}

        final_files = result.get("files", {})
        review_notes = result.get("review_notes", [])
        verification = result.get("verification_result", {})

        # Merge: keep Pro's versions (may have fixes), add any files Pro didn't touch
        for fname, code in generated_files.items():
            if fname not in final_files:
                final_files[fname] = code

        n_issues = len(review_notes)
        n_files = len(final_files)

        if n_issues > 0:
            await emit_event(run_id, "stitch", "warning",
                             f"Pro found {n_issues} issues in generated code, all fixed")
            for note in review_notes[:5]:
                await emit_event(run_id, "stitch", "info",
                                 f"Fixed {note.get('file', '?')}: {note.get('issue', '?')}")

        await emit_event(run_id, "stitch", "success",
                         f"Integration complete: {n_files} files, "
                         f"{verification.get('issues_found', 0)} issues found, "
                         f"{verification.get('issues_fixed', 0)} fixed")

        return {
            "final_files": final_files,
            "review_notes": review_notes,
            "verification_result": verification,
            "current_stage": "compile",
        }

    except Exception as e:
        await emit_event(run_id, "stitch", "error", f"Stitch failed: {e}")
        return {"status": "failed", "errors": [str(e)]}
