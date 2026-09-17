"""Resolve Gleam campaign entry URLs from DB rows."""

from __future__ import annotations

from app.models.giveaway import Giveaway
from app.platforms.gleam import gleam_canonical_url, parse_gleam_campaign_url


def gleam_entry_url(giveaway: Giveaway) -> str | None:
    """Prefer stored entry_url; fall back to classic /<id>/x from campaign id."""
    raw = (giveaway.entry_url or "").strip()
    if raw and "gleam.io" in raw.lower():
        key, _slug = parse_gleam_campaign_url(raw)
        if key:
            return raw
        # Directory shell → classic stub the bot accepts.
        from app.platforms.gleam import parse_gleam_directory_detail_url

        directory_id = parse_gleam_directory_detail_url(raw)
        if directory_id:
            return gleam_canonical_url(directory_id, "x")
    cid = (giveaway.platform_campaign_id or "").strip()
    if cid and giveaway.platform == "gleam":
        return gleam_canonical_url(cid, "x")
    if raw:
        return raw
    return None
