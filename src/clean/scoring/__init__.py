"""Trust-HUD scoring layer for clean-mcp.

Scores AI-agent-written code against the indexed codebase via a registry of
pluggable indicators, and surfaces the result in the terminal.
"""

from __future__ import annotations

from .base import FileScore, Indicator, IndicatorResult, Offender, ScoringContext
from .registry import IndicatorRegistry, register_indicator
from .service import ScoringService
from .state import ScoringStateWriter

__all__ = [
    "FileScore",
    "Indicator",
    "IndicatorResult",
    "Offender",
    "ScoringContext",
    "IndicatorRegistry",
    "register_indicator",
    "ScoringService",
    "ScoringStateWriter",
]
