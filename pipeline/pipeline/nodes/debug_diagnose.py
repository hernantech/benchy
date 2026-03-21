"""Debug pipeline — Stage 3: Gemini analyzes evidence and produces diagnosis."""

from __future__ import annotations

import json
import os
import re

from pipeline.callbacks import emit_event, update_run_status, check_run_status, store_diagnosis
from pipeline.state import DebugPipelineState

GEMINI_PRO = "gemini-3.1-pro-preview"    # deep reasoning for diagnosis
GEMINI_FLASH = "gemini-3-flash-preview"  # fast iteration


async def diagnose_node(state: DebugPipelineState) -> dict:
    run_id = state["run_id"]

    status = await check_run_status(run_id)
    if status in ("cancelled",):
        return {"status": status}

    await update_run_status(run_id, "running", "diagnose")
    await emit_event(run_id, "diagnose", "info", "Analyzing evidence with Gemini...")

    scope = state.get("scope_data", {})
    uart = state.get("uart_data", {})
    psu = state.get("psu_telemetry", {})
    goal = state.get("goal", "diagnose hardware issue")

    # Build evidence summary for Gemini
    stats = scope.get("stats", {})
    evidence = f"""## Hardware Debug Evidence

### Goal
{goal}

### PSU State
- Output voltage: {psu.get('output_voltage', '?')}V
- Output current: {psu.get('output_current', '?')}A
- Output power: {psu.get('output_power', '?')}W
- Mode: {psu.get('mode', '?')} (CV = constant voltage, CC = current limit hit)
- Protection: {psu.get('protection_state', 'none')}

### Scope Measurements
- V_min: {stats.get('v_min', '?')}V
- V_max: {stats.get('v_max', '?')}V
- V_pp (peak-to-peak): {stats.get('v_pp', '?')}V
- V_mean: {stats.get('v_mean', '?')}V

### UART Log
```
{uart.get('data', '(no UART data captured)')[:2000]}
```

### Additional Context
- DUT: ESP32-S3 DevKitC-1 (brownout threshold ~2.44V)
- PSU: FNIRSI DPS-150
- Scope: Digilent Analog Discovery
"""

    try:
        import google.generativeai as genai
        genai.configure(api_key=os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY", ""))
        model = genai.GenerativeModel(GEMINI_PRO)

        prompt = f"""You are an expert embedded systems engineer diagnosing a hardware issue.

Analyze the following evidence from real lab instruments and provide a diagnosis.

{evidence}

Respond in this exact JSON format:
{{
  "summary": "one-sentence summary of the issue",
  "root_cause": "detailed technical root cause",
  "confidence": 0.95,
  "severity": "critical|warning|info",
  "suggested_fix": {{
    "description": "what to change",
    "action": "specific instrument command or config change",
    "psu_voltage": null,
    "psu_current_limit": null
  }},
  "measurements_of_concern": ["v_min below threshold", ...]
}}"""

        response = await model.generate_content_async(prompt)
        text = response.text

        # Extract JSON from response
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            diagnosis = json.loads(match.group())
        else:
            diagnosis = {
                "summary": text[:200],
                "root_cause": text,
                "confidence": 0.5,
                "suggested_fix": None,
            }

        await store_diagnosis(
            run_id,
            model=GEMINI_PRO,
            summary=diagnosis.get("summary", ""),
            root_cause=diagnosis.get("root_cause"),
            confidence=diagnosis.get("confidence"),
            suggested_fix=diagnosis.get("suggested_fix"),
        )

        await emit_event(run_id, "diagnose", "success",
                         f"Diagnosis: {diagnosis.get('summary', 'unknown')}")

        return {
            "diagnosis": diagnosis,
            "current_stage": "fix",
        }

    except Exception as e:
        await emit_event(run_id, "diagnose", "error", f"Gemini analysis failed: {e}")
        return {
            "diagnosis": {"summary": f"Analysis failed: {e}", "root_cause": None, "suggested_fix": None},
            "current_stage": "fix",
            "errors": [str(e)],
        }
