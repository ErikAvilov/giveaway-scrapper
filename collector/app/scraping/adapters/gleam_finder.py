"""GleamFinder International — listing → detail → Gleam campaign URL."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from app.platforms.gleam import gleam_identity_from_url
from app.scraping.adapters.base import (
    PageEnrichment,
    absolute_url,
    anchor_pairs,
    body_text,
    css_attr,
    dedupe_urls,
    first_css_text,
)
from app.scraping.listing_filters import is_worldwide_text

_DETAIL_RE = re.compile(r"^/giveaway/[A-Za-z0-9]+/[^/]+/?$", re.IGNORECASE)
_CATEGORY_RE = re.compile(r"^/category/", re.IGNORECASE)


class GleamFinderAdapter:
    key = "gleam_finder"

    def enrich(self, response: Any, *, page_url: str) -> PageEnrichment:
        path = urlparse(page_url).path or "/"
        is_detail = bool(_DETAIL_RE.match(path))

        if not is_detail:
            follow: list[str] = []
            for href in css_attr(response, 'a[href*="/giveaway/"]::attr(href)'):
                abs_url = absolute_url(page_url, href)
                if not abs_url:
                    continue
                p = urlparse(abs_url).path or ""
                if _DETAIL_RE.match(p):
                    follow.append(abs_url)
            return PageEnrichment(
                skip_as_candidate=True,
                follow_urls=dedupe_urls(follow) or None,
                meta={"hub": "category" if _CATEGORY_RE.match(path) else "listing"},
            )

        title = first_css_text(response, ("h1", ".card-title", "title"))
        body = body_text(response)
        organizer = None
        m = re.search(r"by\s+([^\n]+)", body)
        if m:
            organizer = m.group(1).strip()[:200]
        end_date = None
        m = re.search(
            r"(?:Giveaway runs|Ends?|End date)[:\s]+([^\n]+)",
            body,
            re.IGNORECASE,
        )
        if m:
            end_date = m.group(1).strip()[:120]
        restriction = None
        if is_worldwide_text(body) or "open worldwide" in body.lower():
            restriction = "Worldwide"
        elif m_r := re.search(r"(Open [^\n]{0,80})", body, re.IGNORECASE):
            restriction = m_r.group(1).strip()[:200]

        prize = None
        m = re.search(r"PRIZE\s*\n(.+)", body, re.IGNORECASE)
        if m:
            prize = m.group(1).strip().split("\n")[0][:300]

        entry_url = None
        for href, text in anchor_pairs(response):
            abs_url = absolute_url(page_url, href)
            if not abs_url:
                continue
            if "gleam.io/" in abs_url:
                entry_url = abs_url
                break
            if "enter" in (text or "").lower() and "gleam" in (text or "").lower():
                entry_url = abs_url
                break

        meta: dict[str, Any] = {}
        if entry_url:
            identity = gleam_identity_from_url(entry_url)
            if identity:
                meta.update(identity)

        return PageEnrichment(
            title=title,
            prize=prize,
            end_date_text=end_date,
            entry_url=entry_url,
            organizer=organizer,
            restriction_text=restriction,
            excerpt=body[:3000] if body else None,
            skip_as_candidate=False,
            meta=meta,
        )
