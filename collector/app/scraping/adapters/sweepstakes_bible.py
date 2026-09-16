"""SweepstakesBible — Worldwide tag listing + detail metadata."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from app.platforms.gleam import gleam_identity_from_url
from app.platforms.sweepwidget import sweepwidget_identity_from_url
from app.scraping.adapters.base import (
    PageEnrichment,
    absolute_url,
    anchor_pairs,
    body_text,
    css_attr,
    dedupe_urls,
    first_css_text,
)
from app.scraping.listing_filters import category_is_wanted, is_worldwide_text

_DETAIL_RE = re.compile(r"^/giveaways/[a-z0-9\-]+/?$", re.IGNORECASE)


class SweepstakesBibleAdapter:
    key = "sweepstakes_bible"

    def enrich(self, response: Any, *, page_url: str) -> PageEnrichment:
        path = urlparse(page_url).path or "/"
        is_detail = bool(_DETAIL_RE.match(path))

        if not is_detail:
            follow: list[str] = []
            for href in css_attr(
                response,
                'article a[href*="/giveaways/"]::attr(href), a[href*="/giveaways/"]::attr(href)',
            ):
                abs_url = absolute_url(page_url, href)
                if not abs_url:
                    continue
                p = urlparse(abs_url).path or ""
                if _DETAIL_RE.match(p):
                    follow.append(abs_url)
            return PageEnrichment(
                skip_as_candidate=True,
                follow_urls=dedupe_urls(follow) or None,
                meta={"hub": "tags" if "/tags/" in path else "listing"},
            )

        title = first_css_text(response, ("h1", "title"))
        body = body_text(response)
        entry_type = _meta(body, "Entry Type")
        prize_type = _meta(body, "Prize Type")
        arv = _meta(body, "Total ARV")
        end_date = _meta(body, "End Date")
        restriction = "Worldwide" if is_worldwide_text(body) else None

        entry_url = None
        for href, text in anchor_pairs(response):
            abs_url = absolute_url(page_url, href)
            if not abs_url:
                continue
            label = (text or "").lower()
            if (
                ("enter to win" in label or label.strip() == "enter")
                and "sweepstakesbible.com" not in abs_url
            ):
                entry_url = abs_url
                break
            if any(
                h in abs_url
                for h in ("gleam.io/", "sweepwidget.com/", "viralsweep.com/")
            ):
                entry_url = abs_url
                break

        prize = prize_type
        if arv:
            prize = f"{prize_type or 'Prize'} ({arv})" if prize_type else arv

        meta: dict[str, Any] = {
            "entry_type": entry_type,
            "prize_type": prize_type,
            "arv": arv,
        }
        if entry_url:
            identity = gleam_identity_from_url(entry_url) or sweepwidget_identity_from_url(
                entry_url
            )
            if identity:
                meta.update(identity)

        skip = category_is_wanted(prize_type or title or "") is False

        return PageEnrichment(
            title=title,
            prize=prize,
            end_date_text=end_date,
            entry_url=entry_url,
            restriction_text=restriction,
            entry_method_text=entry_type,
            excerpt=body[:3000] if body else None,
            skip_as_candidate=skip,
            meta=meta,
        )


def _meta(body: str, label: str) -> str | None:
    m = re.search(rf"{re.escape(label)}\s*:\s*([^\n]+)", body, re.IGNORECASE)
    return m.group(1).strip()[:200] if m else None
