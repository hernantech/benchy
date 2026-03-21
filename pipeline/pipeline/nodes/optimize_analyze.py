"""Optimize pipeline — Stage 1: Analyze source code for optimization opportunities."""

from __future__ import annotations

import json
import os
import re

from pipeline.callbacks import emit_event, update_run_status, check_run_status
from pipeline.state import OptimizePipelineState

GEMINI_PRO = "gemini-3.1-pro-preview"    # deep reasoning for ISA analysis
GEMINI_FLASH = "gemini-3-flash-preview"  # fast iteration

# ISA optimization playbook — injected into prompt
XTENSA_PLAYBOOK = """## ESP32-S3 Xtensa LX7 Optimization Playbook

### Hardware Capabilities
- Dual-core 240MHz Xtensa LX7
- 128-bit SIMD / vector extensions (PIE)
- Hardware multiply-accumulate (MAC) units
- 512KB internal SRAM (fast) + 8MB PSRAM (5-10x slower)

### Pattern: Dot Product / FIR / MAC Loop
- Symptom: `for(i=0;i<N;i++) acc += a[i] * b[i]`
- Transform: use `dsps_dotprod_f32_ae32()` from esp-dsp
- Requirements: 16-byte aligned arrays, data in internal SRAM
- Expected speedup: 3-5x
- Alignment: `__attribute__((aligned(16)))`
- SRAM placement: `DMA_ATTR` or avoid `EXT_RAM_BSS_ATTR`

### Pattern: Matrix Multiply / Conv2D
- Symptom: nested loops with element-wise multiply-accumulate
- Transform: esp-nn kernels for int8, esp-dsp for float
- Requirements: quantized weights, aligned buffers
- Expected speedup: 4-8x for int8

### Pattern: Memory Placement
- SRAM (512KB): fast, use for hot data and coefficient buffers
- PSRAM (8MB): 5-10x slower, use for cold storage only
- Symptom: large arrays default to PSRAM via compiler
- Transform: explicitly place hot buffers in SRAM with `DMA_ATTR`

### Pattern: Loop Unrolling
- Manual 4x unrolling helps the compiler vectorize
- Process 4 elements per iteration to match 128-bit SIMD width (4x float32)

### Anti-patterns
- Unaligned SIMD loads → hardware exception (LoadStoreAlignmentCause)
- PSRAM + tight loop → cache thrashing, 5-10x slower
- Float in inner loop when int8/int16 suffices → missed SIMD opportunity
- Division in inner loop → use reciprocal multiply instead
"""


async def analyze_node(state: OptimizePipelineState) -> dict:
    run_id = state["run_id"]
    source_code = state.get("source_code", "")
    goal = state.get("goal", "optimize for ESP32-S3")

    status = await check_run_status(run_id)
    if status in ("cancelled",):
        return {"status": status}

    await update_run_status(run_id, "running", "analyze")
    await emit_event(run_id, "analyze", "info", "Analyzing code for optimization opportunities...")

    prompt = f"""You are an expert embedded systems performance engineer specializing in the ESP32-S3 Xtensa LX7 architecture.

{XTENSA_PLAYBOOK}

## User Goal
{goal}

## Source Code to Analyze
```c
{source_code[:8000]}
```

Analyze this code and identify ALL optimization opportunities for the ESP32-S3.

Respond in this exact JSON format:
{{
  "description": "what this code does in one sentence",
  "hotspots": ["list of performance-critical sections"],
  "current_complexity": "O(n) / O(n^2) / etc",
  "optimization_opportunities": [
    {{
      "location": "line or function name",
      "issue": "what's suboptimal",
      "isa_pattern": "which playbook pattern applies",
      "expected_speedup": "2-4x",
      "transform": "what to change"
    }}
  ],
  "memory_issues": ["any alignment or placement problems"],
  "estimated_total_speedup": "3-5x"
}}"""

    try:
        import google.generativeai as genai
        genai.configure(api_key=os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY", ""))
        model = genai.GenerativeModel(GEMINI_PRO)  # deep reasoning for ISA analysis

        response = await model.generate_content_async(prompt)
        text = response.text

        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            analysis = json.loads(match.group())
        else:
            analysis = {"description": text[:300], "optimization_opportunities": []}

        n_opps = len(analysis.get("optimization_opportunities", []))
        await emit_event(run_id, "analyze", "success",
                         f"Found {n_opps} optimization opportunities. "
                         f"Estimated speedup: {analysis.get('estimated_total_speedup', 'unknown')}")

        return {
            "analysis": analysis,
            "current_stage": "optimize",
        }

    except Exception as e:
        await emit_event(run_id, "analyze", "error", f"Analysis failed: {e}")
        return {"status": "failed", "errors": [str(e)]}
