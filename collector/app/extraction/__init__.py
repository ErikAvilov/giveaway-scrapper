"""Giveaway extraction from crawled page content."""

from __future__ import annotations

from app.extraction.entry_assessment import (
    EntryAssessment,
    EntryFriction,
    GeoScope,
    assess_entry,
    classify_entry_friction,
    detect_undesirable,
    infer_eligible_france,
    infer_geo_scope,
)

__all__ = [
    "EntryAssessment",
    "EntryFriction",
    "GeoScope",
    "assess_entry",
    "classify_entry_friction",
    "detect_undesirable",
    "infer_eligible_france",
    "infer_geo_scope",
]
