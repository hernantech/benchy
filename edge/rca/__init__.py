"""
BenchCI Root Cause Analysis (RCA) Module

Three-tier architecture:
  Tier 1 — Signal Processing Pipeline (deterministic EE calculations)
  Tier 2 — Context-Aware Subagent (rule-based hypothesis generation with board docs)
  Tier 3 — Gemini Chat Agent (the UI chat agent IS the decision maker)

The RCAPipeline runs Tier 1 + Tier 2 and returns structured data.
The Gemini agent in the chat UI acts as Tier 3 — it receives the analysis
results as a tool response and decides what to do next.
"""

from .signal_processing import SignalProcessor
from .context_analyzer import ContextAnalyzer
from .orchestrator import RCAPipeline, RCASession
from .report import RCAReportGenerator

__all__ = [
    "SignalProcessor",
    "ContextAnalyzer",
    "RCAPipeline",
    "RCASession",
    "RCAReportGenerator",
]
