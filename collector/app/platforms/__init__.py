"""Giveaway hosting platforms (Gleam, etc.) — not discovery aggregators."""

from __future__ import annotations

from app.platforms.gleam import (
    PLATFORM,
    GleamCampaign,
    gleam_identity_from_url,
    is_gleam_host,
    parse_gleam_campaign_html,
    parse_gleam_campaign_url,
)

__all__ = [
    "PLATFORM",
    "GleamCampaign",
    "gleam_identity_from_url",
    "is_gleam_host",
    "parse_gleam_campaign_html",
    "parse_gleam_campaign_url",
]
