"""Gleam.io platform adapter — directory discovery + classic campaign pages."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.platforms.gleam import (
    diagnose_gleam_parse_failure,
    extract_campaign_widget_url,
    gleam_canonical_url,
    gleam_identity_from_url,
    is_gleam_directory_listing,
    parse_gleam_campaign_html,
    parse_gleam_campaign_url,
    parse_gleam_directory_detail_url,
    response_html,
)
from app.platforms.gleam_directory import directory_follow_plan
from app.scraping.adapters.base import PageEnrichment, dedupe_urls


class GleamAdapter:
    """Reusable Gleam campaign + public directory discovery adapter."""

    key = "gleam"

    def enrich(self, response: Any, *, page_url: str) -> PageEnrichment:
        path = urlparse(page_url).path or "/"

        # --- Public directory listing ---
        if is_gleam_directory_listing(page_url):
            return self._enrich_directory_listing(response, page_url=page_url)

        # --- Directory detail /giveaways/<id> → follow classic widget URL ---
        directory_id = parse_gleam_directory_detail_url(page_url)
        if directory_id:
            return self._enrich_directory_detail(
                response, page_url=page_url, directory_id=directory_id
            )

        # --- Classic campaign /<key>/<slug> ---
        key, _slug = parse_gleam_campaign_url(page_url)
        if key is None:
            return PageEnrichment(
                skip_as_candidate=True,
                follow_urls=[],
                meta={"gleam_non_campaign": True, "path": path},
            )

        return self._enrich_classic_campaign(response, page_url=page_url)

    def _directory_max_pages(self, response: Any) -> int:
        raw = getattr(response, "_gleam_directory_max_pages", None)
        if raw is not None:
            try:
                return max(1, int(raw))
            except (TypeError, ValueError):
                pass
        meta = getattr(response, "meta", None) or {}
        raw = meta.get("gleam_directory_max_pages") if isinstance(meta, dict) else None
        if raw is not None:
            try:
                return max(1, int(raw))
            except (TypeError, ValueError):
                pass
        return 5

    def _enrich_directory_listing(self, response: Any, *, page_url: str) -> PageEnrichment:
        html = response_html(response) or ""
        max_pages = self._directory_max_pages(response)
        plan = directory_follow_plan(
            html, page_url=page_url, max_listing_pages=max_pages
        )
        follow = dedupe_urls(list(plan["follow_urls"]))
        detail_urls = list(plan["detail_urls"])
        return PageEnrichment(
            skip_as_candidate=True,
            follow_urls=follow or [],
            meta={
                "gleam_directory": True,
                "gleam_directory_listing": True,
                "giveaway_links_discovered": plan["giveaway_links_discovered"],
                "giveaway_detail_pages_scheduled": len(detail_urls),
                "listing_pages_queued": len(plan["listing_urls"]),
                "follow_count": len(follow),
                "sample_titles": [c.title for c in plan["cards"][:10] if c.title],
                "sample_detail_urls": detail_urls[:10],
                "priority_prize_cards": sum(
                    1 for c in plan["cards"] if c.priority_prize_hint
                ),
                "follow_kind": "directory_detail",
            },
        )

    def _enrich_directory_detail(
        self,
        response: Any,
        *,
        page_url: str,
        directory_id: str,
    ) -> PageEnrichment:
        html = response_html(response) or ""
        widget = extract_campaign_widget_url(html)
        classic = widget or gleam_canonical_url(directory_id, "x")
        identity = gleam_identity_from_url(page_url) or {
            "platform": "gleam",
            "platform_campaign_id": directory_id,
        }
        detail_shape = "widget" if widget else "fallback_classic"
        # Do not emit directory shell as the final candidate — follow classic page
        # which carries initCampaign actions / geo / friction.
        return PageEnrichment(
            skip_as_candidate=True,
            follow_urls=dedupe_urls([classic]),
            title=_css_title(response),
            entry_url=classic,
            meta={
                **identity,
                "gleam_directory_detail": True,
                "directory_id": directory_id,
                "classic_follow": classic,
                "widget_url": widget,
                "directory_detail_shape": detail_shape,
                "platform": "gleam",
                "platform_campaign_id": directory_id,
                "follow_kind": "classic_campaign",
            },
        )

    def _enrich_classic_campaign(self, response: Any, *, page_url: str) -> PageEnrichment:
        html = response_html(response)
        http_status = _http_status(response)
        campaign = parse_gleam_campaign_html(html, page_url=page_url)
        identity = gleam_identity_from_url(page_url) or {}

        if campaign is None:
            reason = diagnose_gleam_parse_failure(
                html, page_url=page_url, http_status=http_status
            )
            return PageEnrichment(
                skip_as_candidate=False,
                entry_url=identity.get("entry_url") or page_url,
                excerpt=None,
                follow_urls=[],
                meta={
                    **identity,
                    "platform": "gleam",
                    "parse_status": "payload_missing",
                    "parse_failure_reason": reason,
                    "gleam_classic_campaign": True,
                    "http_status": http_status,
                },
            )

        instructions = _instructions_summary(campaign)
        meta = campaign.to_meta()
        meta["parse_status"] = "ok"
        meta["parse_failure_reason"] = None
        meta["gleam_classic_campaign"] = True
        meta["http_status"] = http_status
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
            terms_url=None,
            organizer=campaign.organizer,
            restriction_text=campaign.geo_restriction,
            entry_method_text=instructions,
            excerpt=_excerpt(campaign),
            skip_as_candidate=False,
            follow_urls=[],
            meta=meta,
        )


def _http_status(response: Any) -> int | None:
    for attr in ("status", "status_code", "statusCode"):
        raw = getattr(response, attr, None)
        if raw is None:
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return None


def _css_title(response: Any) -> str | None:
    try:
        nodes = response.css("title::text")
        if nodes:
            text = str(nodes[0]).strip()
            return text[:300] or None
    except (TypeError, ValueError, AttributeError):
        pass
    return None


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
    chunks: list[str] = []
    if campaign.title:
        chunks.append(campaign.title)
    if campaign.prize:
        chunks.append(f"Prize: {campaign.prize}")
    if campaign.organizer:
        chunks.append(f"Organizer: {campaign.organizer}")
    if campaign.geo_restriction:
        chunks.append(f"Eligibility: {campaign.geo_restriction}")
    if campaign.terms_text:
        chunks.append(campaign.terms_text[:1200])
    for action in campaign.mandatory_actions[:8]:
        chunks.append(f"Required: {action.entry_type}")
    for action in campaign.optional_actions[:8]:
        chunks.append(f"Optional: {action.entry_type}")
    return "\n".join(chunks)[:3000]
