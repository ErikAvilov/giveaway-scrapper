"""Gemini API integration."""

from app.gemini.client import GeminiAnalysisResult, GeminiClient, GeminiUsage
from app.gemini.schema import EntryMethod, GiveawayAnalysis
from app.gemini.service import (
    AnalyzeAllResult,
    AnalyzeBatchResult,
    analyze_all_pending,
    analyze_giveaways,
    decide_status,
)

__all__ = [
    "AnalyzeAllResult",
    "AnalyzeBatchResult",
    "EntryMethod",
    "GeminiAnalysisResult",
    "GeminiClient",
    "GeminiUsage",
    "GiveawayAnalysis",
    "analyze_all_pending",
    "analyze_giveaways",
    "decide_status",
]
