"""State TypedDicts for both hackathon pipelines."""

from typing import TypedDict


class DebugPipelineState(TypedDict):
    """Hardware debug pipeline — diagnose power/signal/protocol issues."""

    # Identity (set at init, read by all nodes)
    run_id: str
    callback_url: str        # Supabase or frontend webhook for events
    runner_url: str           # Pi worker HTTP base URL

    # User intent
    goal: str                 # e.g. "find brownout threshold", "verify I2C signal integrity"
    instructions: str         # optional user instructions

    # Stage 1: Setup — configure instruments
    psu_config: dict          # {voltage, current_limit}
    dut_config: dict          # commands to send to DUT (e.g. wifi_connect)

    # Stage 2: Capture — collect measurements
    scope_data: dict          # {stats, chart_url, data (truncated)}
    uart_data: dict           # {data (text), bytes}
    psu_telemetry: dict       # {voltage, current, power, mode, protection}

    # Stage 3: Diagnose — Gemini analyzes evidence
    diagnosis: dict           # {summary, root_cause, confidence, suggested_fix}

    # Stage 4: Fix — apply suggested fix, re-capture
    fix_applied: dict         # what was changed
    retest_result: dict       # second capture results
    comparison: dict          # before vs after

    # Control
    status: str               # queued|running|completed|failed|cancelled
    current_stage: str        # setup|capture|diagnose|fix|retest
    errors: list[str]


class FirmwarePipelineState(TypedDict):
    """Firmware generation pipeline — Pro architects, Flash Lite generates, Pro stitches+verifies."""

    # Identity
    run_id: str
    callback_url: str
    runner_url: str

    # User intent
    goal: str                 # e.g. "FIR filter optimized for ESP32-S3 with benchmark harness"
    source_code: str          # existing code to optimize (optional)
    reference_docs: str       # datasheets, API docs, ISA reference
    isa_playbook: str         # ESP32-S3 optimization playbook
    target: str               # "esp32s3"
    project_path: str         # path on Pi for firmware project

    instructions: str

    # Stage 1: Architect (Pro) — reads docs, produces spec + subtasks
    architecture_spec: dict   # {description, modules, dependencies, memory_strategy, ...}
    subtasks: list[dict]      # [{id, file, description, spec, depends_on}, ...]
    integration_spec: dict    # {main_cpp_structure, command_interface, benchmark_protocol}
    verification_checklist: list[str]

    # Stage 2: Generate (Flash Lite workers) — parallel code generation
    generated_files: dict     # {filename: code_string}

    # Stage 3: Stitch (Pro) — integrates, writes main.cpp, verifies
    final_files: dict         # {filename: code_string} — corrected + main.cpp + platformio.ini
    review_notes: list[dict]  # [{file, issue, fix}]
    verification_result: dict

    # Stage 4: Compile — write to disk, build, fix errors iteratively
    compiled_files: dict      # final versions after compile fixes
    compile_result: dict
    compile_attempts: int

    # Stage 5: Flash + Test — deploy and benchmark
    test_results: dict        # {baseline: {...}, optimized: {...}}

    # Control
    status: str
    current_stage: str        # architect|generate|stitch|compile|flash|complete
    errors: list[str]


class OptimizePipelineState(TypedDict):
    """ISA-aware firmware optimization pipeline — analyze, optimize, benchmark."""

    # Identity
    run_id: str
    callback_url: str
    runner_url: str

    # User intent
    goal: str                 # e.g. "optimize this FIR filter for ESP32-S3"
    source_code: str          # C/C++ code to optimize
    instructions: str

    # Stage 1: Analyze — understand the code and identify optimization opportunities
    analysis: dict            # {description, hotspots, current_complexity, optimization_opportunities}

    # Stage 2: Optimize — generate optimized version using ISA knowledge
    optimized_code: str       # the optimized C/C++ code
    optimization_rationale: str  # why each change was made
    isa_patterns_used: list[str]  # e.g. ["esp-dsp dotprod", "16-byte alignment", "SRAM placement"]

    # Stage 3: Baseline benchmark — measure original code
    baseline_result: dict     # {total_ms, per_iteration_us, power, chart_url, esp32_report}

    # Stage 4: Optimized benchmark — measure optimized code
    optimized_result: dict    # same shape as baseline

    # Stage 5: Compare — generate comparison report
    comparison: dict          # {speedup_x, power_reduction_pct, correctness, summary}

    # Control
    status: str
    current_stage: str        # analyze|optimize|baseline|benchmark|compare
    errors: list[str]
