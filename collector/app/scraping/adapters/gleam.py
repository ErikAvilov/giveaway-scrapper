"""Gleam.io platform adapter — parses campaign pages when crawled directly."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.platforms.gleam import (
    gleam_identity_from_url,
    parse_gleam_campaign_html,
    parse_gleam_campaign_url,
    response_html,
)
from app.scraping.adapters.base import PageEnrichment


class GleamAdapter:
    """Reusable Gleam campaign parser exposed through the adapter registry."""

    key = "gleam"

    def enrich(self, response: Any, *, page_url: str) -> PageEnrichment:
        path = urlparse(page_url).path or "/"
        key, _slug = parse_gleam_campaign_url(page_url)
        # Marketing / app pages — not campaigns.
        if key is None:
            return PageEnrichment(
                skip_as_candidate=True,
                follow_urls=None,
                meta={"gleam_non_campaign": True, "path": path},
            )

        html = response_html(response)
        campaign = parse_gleam_campaign_html(html, page_url=page_url)
        identity = gleam_identity_from_url(page_url) or {}

        if campaign is None:
            # URL is a campaign shape but payload missing (JS shell / block).
            return PageEnrichment(
                skip_as_candidate=False,
                entry_url=identity.get("entry_url") or page_url,
                excerpt=None,
                meta={
                    **identity,
                    "platform": "gleam",
                    "parse_status": "payload_missing",
                },
            )

        instructions = _instructions_summary(campaign)
        meta = campaign.to_meta()
        meta["parse_status"] = "ok"
        meta["organizer_url"] = campaign.organizer_url
        meta["start_at"] = campaign.start_at.isoformat() if campaign.start_at else None
        meta["end_at"] = campaign.end_at.isoformat() if campaign.end_at else None
        meta["free_hint"] = campaign.free_entry
        meta["purchase_required_text"] = (
            "No" if campaign.free_entry is True else ("Yes" if campaign.free_entry is False else None)
        )
        meta["expired"] = bool(campaign.finished)
        meta["entry_friction_override"] = campaign.entry_friction
        meta["platform"] = "gleam"
        meta["platform_campaign_id"] = campaign.platform_campaign_id

        return PageEnrichment(
            title=campaign.title,
            prize=campaign.prize,
            end_date_text=campaign.end_at.isoformat() if campaign.end_at else None,
            entry_url=campaign.entry_url or page_url,
            terms_url=None,  # terms are inline HTML, not a separate URL
            organizer=campaign.organizer,
            restriction_text=campaign.geo_restriction,
            entry_method_text=instructions,
            excerpt=_excerpt(campaign),
            skip_as_candidate=False,
            follow_urls=None,
            meta=meta,
        )


def _instructions_summary(campaign: Any) -> str:
    parts: list[str] = []
    if campaign.actions_required is not None:
        parts.append(f"actions_required={campaign.actions_required}")
    if campaign.mandatory_actions:
        parts.append(
            "mandatory:" + ",".join(a.entry_type for a in campaign.mandatory_actions)
        )
    if campaign.optional_actions:
        parts.append(
            "optional:"
            + ",".join(a.entry_type for a in campaign.optional_actions[:12])
        )
    if campaign.login_required:
        parts.append("login_required")
    if campaign.referral_actions:
        parts.append("referral:" + ",".join(a.entry_type for a in campaign.referral_actions))
    if campaign.upload_actions:
        parts.append("upload:" + ",".join(a.entry_type for a in campaign.upload_actions))
    return "; ".join(parts) if parts else "gleam_campaign"


def _excerpt(campaign: Any) -> str:
    chunks = [
        campaign.title or "",
        campaign.description or "",
        f"Organizer: {campaign.organizer}" if campaign.organizer else "",
        f"Restriction: {campaign.geo_restriction}" if campaign.geo_restriction else "",
        _instructions_summary(campaign),
        (campaign.terms_text or "")[:1200],
    ]
    return "\n".join(c for c in chunks if c)[:3000]
