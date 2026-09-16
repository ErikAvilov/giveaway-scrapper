"""GiveawayBase adapter — one adapter for worldwide/gaming/pc/console/technology."""

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
from app.scraping.listing_filters import is_worldwide_text

_CATEGORY_RE = re.compile(r"^/category/", re.IGNORECASE)
_AUTHOR_RE = re.compile(r"/author/", re.IGNORECASE)
_SKIP = ("/tag/", "/page/", "/submit", "/best-of")


class GiveawayBaseAdapter:
    key = "giveaway_base"

    def enrich(self, response: Any, *, page_url: str) -> PageEnrichment:
        path = urlparse(page_url).path or "/"
        is_category = bool(_CATEGORY_RE.match(path)) or path in {"", "/"}
        is_detail = not is_category and not any(s in path for s in _SKIP)

        if is_category or not is_detail:
            follow: list[str] = []
            for href in css_attr(
                response, "article h2 a::attr(href), .entry-title a::attr(href), h2 a::attr(href)"
            ):
                abs_url = absolute_url(page_url, href)
                if not abs_url or _AUTHOR_RE.search(abs_url):
                    continue
                p = urlparse(abs_url).path or ""
                if _CATEGORY_RE.match(p) or any(s in p for s in _SKIP):
                    continue
                if abs_url.rstrip("/").endswith("giveawaybase.com"):
                    continue
                follow.append(abs_url)
            return PageEnrichment(
                skip_as_candidate=True,
                follow_urls=dedupe_urls(follow) or None,
                meta={"hub": "category" if is_category else "listing"},
            )

        title = first_css_text(response, ("h1", ".entry-title", "title"))
        body = body_text(response)
        end_date = _field(body, "GIVEAWAY END")
        open_to = _field(body, "OPEN TO")
        prize = _field(body, "GIVEAWAY PRIZE") or _prize_fallback(body)
        requirements = _section_after(body, "GIVEAWAY REQUIREMENTS")

        entry_url = None
        for href, text in anchor_pairs(response):
            abs_url = absolute_url(page_url, href)
            if not abs_url:
                continue
            label = (text or "").lower()
            if any(
                h in abs_url
                for h in (
                    "gleam.io/",
                    "sweepwidget.com/",
                    "viralsweep.com/",
                    "woobox.com/",
                    "kingsumo.com/",
                )
            ):
                entry_url = abs_url
                break
            if "enter" in label and "giveawaybase.com" not in abs_url:
                entry_url = abs_url
                break

        meta: dict[str, Any] = {
            "open_to": open_to,
            "requirements": (requirements or "")[:500] or None,
        }
        if entry_url:
            identity = gleam_identity_from_url(entry_url) or sweepwidget_identity_from_url(
                entry_url
            )
            if identity:
                meta.update(identity)

        # Hard preference: reject explicit non-worldwide OPEN TO at adapter level
        # by skipping candidate (spider still classifies; we set skip when clear US/UK).
        skip = False
        skip_reasons: list[str] = []
        if open_to and not is_worldwide_text(open_to):
            low = open_to.lower()
            if any(
                x in low
                for x in (
                    "united states",
                    "usa",
                    "us only",
                    "uk only",
                    "united kingdom",
                    "canada",
                    "australia",
                )
            ):
                skip = True
                skip_reasons.append("open_to_not_worldwide")

        return PageEnrichment(
            title=title,
            prize=prize,
            end_date_text=end_date,
            entry_url=entry_url,
            restriction_text=open_to,
            entry_method_text=requirements[:300] if requirements else None,
            excerpt=body[:3000] if body else None,
            skip_as_candidate=skip,
            meta={**meta, "skip_reasons": skip_reasons} if skip_reasons else meta,
        )


def _field(body: str, label: str) -> str | None:
    m = re.search(
        rf"{re.escape(label)}\s*[:\|]?\s*([^\n]+)",
        body,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()[:300]
    return None


def _section_after(body: str, label: str) -> str | None:
    m = re.search(
        rf"{re.escape(label)}\s*\n(.+?)(?:\nGIVEAWAY |\nOPEN TO|\nGIVEAWAY END|\Z)",
        body,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        return m.group(1).strip()[:800]
    return None


def _prize_fallback(body: str) -> str | None:
    m = re.search(r"GIVEAWAY PRIZE\s*\n(.+)", body, re.IGNORECASE)
    if m:
        return m.group(1).strip().split("\n")[0][:300]
    return None
