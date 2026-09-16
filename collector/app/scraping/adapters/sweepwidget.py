"""SweepWidget public giveaway directory + campaign pages."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.platforms.sweepwidget import (
    parse_sweepwidget_campaign_html,
    parse_sweepwidget_campaign_url,
    response_html,
    sweepwidget_identity_from_url,
)
from app.scraping.adapters.base import (
    PageEnrichment,
    absolute_url,
    css_attr,
    dedupe_urls,
)


class SweepWidgetAdapter:
    key = "sweepwidget"

    def enrich(self, response: Any, *, page_url: str) -> PageEnrichment:
        path = urlparse(page_url).path or "/"
        cid, _slug = parse_sweepwidget_campaign_url(page_url)

        # Directory / listing
        if cid is None:
            follow: list[str] = []
            for href in css_attr(response, 'a[href*="/giveaways/"]::attr(href)'):
                abs_url = absolute_url(page_url, href)
                if not abs_url:
                    continue
                camp_id, _ = parse_sweepwidget_campaign_url(abs_url)
                if camp_id:
                    follow.append(abs_url)
            return PageEnrichment(
                skip_as_candidate=True,
                follow_urls=dedupe_urls(follow) or None,
                meta={"hub": "directory", "path": path},
            )

        html = response_html(response)
        campaign = parse_sweepwidget_campaign_html(html, page_url=page_url)
        identity = sweepwidget_identity_from_url(page_url) or {}

        if campaign is None:
            return PageEnrichment(
                skip_as_candidate=False,
                entry_url=identity.get("entry_url") or page_url,
                meta={**identity, "parse_status": "payload_missing"},
            )

        meta = campaign.to_meta()
        meta["parse_status"] = "ok"
        meta["expired"] = bool(campaign.finished)
        # Geo often missing on directory campaigns — leave unknown (never assume WW).
        return PageEnrichment(
            title=campaign.title,
            prize=campaign.prize,
            end_date_text=campaign.end_date_text,
            entry_url=campaign.entry_url or page_url,
            restriction_text=campaign.geo_restriction,
            excerpt=campaign.excerpt,
            skip_as_candidate=False,
            meta=meta,
        )
