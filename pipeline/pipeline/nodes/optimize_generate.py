"""Optimize pipeline — Stage 2: Generate optimized code using ISA knowledge."""

from __future__ import annotations

import json
import os
import re

from pipeline.callbacks import emit_event, update_run_status, check_run_status
from pipeline.nodes.optimize_analyze import XTENSA_PLAYBOOK
from pipeline.state import OptimizePipelineState

GEMINI_FLASH = "gemini-3-flash-preview"  # fast code generation


async def optimize_node(state: OptimizePipelineState) -> dict:
    run_id = state["run_id"]
    source_code = state.get("source_code", "")
    analysis = state.get("analysis", {})
    instructions = state.get("instructions", "")

    status = await check_run_status(run_id)
    if status in ("cancelled",):
        return {"status": status}

    await update_run_status(run_id, "running", "optimize")
    await emit_event(run_id, "optimize", "info", "Generating optimized code...")

    opps = json.dumps(analysis.get("optimization_opportunities", []), indent=2)

    prompt = f"""You are an expert ESP32-S3 performance engineer. Generate an optimized version of this code.

{XTENSA_PLAYBOOK}

## Original Code
```c
{source_code[:6000]}
```

## Identified Optimization Opportunities
{opps}

## Additional Instructions
{instructions or 'None'}

## Requirements
1. The optimized code MUST produce the same output as the original (bit-exact for integers, within 1e-6 for floats)
2. Use esp-dsp library functions where applicable (e.g., dsps_dotprod_f32_ae32)
3. Add 16-byte alignment attributes where needed
4. Place hot data in SRAM (use DMA_ATTR or __attribute__((section(".dram1"))))
5. The code must compile with Arduino/ESP-IDF for ESP32-S3
6. Include necessary #include directives

Respond in this exact format:

OPTIMIZED_CODE:
```c
// your optimized code here
```

RATIONALE:
<explain each change and which ISA feature it leverages>

ISA_PATTERNS:
<comma-separated list of patterns used, e.g.: "esp-dsp dotprod, 16-byte alignment, SRAM placement">
"""

    try:
        import google.generativeai as genai
        genai.configure(api_key=os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY", ""))
        model = genai.GenerativeModel(GEMINI_FLASH)  # fast code gen iteration

        response = await model.generate_content_async(prompt)
        text = response.text

        # Extract code block
        code_match = re.search(r"OPTIMIZED_CODE:\s*```(?:c|cpp)?\s*([\s\S]*?)```", text)
        optimized_code = code_match.group(1).strip() if code_match else ""

        # Extract rationale
        rat_match = re.search(r"RATIONALE:\s*([\s\S]*?)(?:ISA_PATTERNS:|$)", text)
        rationale = rat_match.group(1).strip() if rat_match else ""

        # Extract ISA patterns
        pat_match = re.search(r"ISA_PATTERNS:\s*(.*?)$", text, re.MULTILINE)
        patterns_str = pat_match.group(1).strip() if pat_match else ""
        isa_patterns = [p.strip() for p in patterns_str.split(",") if p.strip()]

        if not optimized_code:
            # Fallback: try to find any code block
            fallback = re.search(r"```(?:c|cpp)?\s*([\s\S]*?)```", text)
            if fallback:
                optimized_code = fallback.group(1).strip()
                rationale = text
                isa_patterns = ["unknown"]

        if not optimized_code:
            await emit_event(run_id, "optimize", "error", "Failed to extract optimized code from Gemini response")
            return {"status": "failed", "errors": ["No code generated"]}

        await emit_event(run_id, "optimize", "success",
                         f"Generated optimized code. Patterns: {', '.join(isa_patterns) or 'none identified'}")

        return {
            "optimized_code": optimized_code,
            "optimization_rationale": rationale,
            "isa_patterns_used": isa_patterns,
            "current_stage": "baseline",
        }

    except Exception as e:
        await emit_event(run_id, "optimize", "error", f"Code generation failed: {e}")
        return {"status": "failed", "errors": [str(e)]}
