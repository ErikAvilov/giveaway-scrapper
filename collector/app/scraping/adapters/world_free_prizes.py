"""WorldFreePrizes — prefer Worldwide + wanted categories."""

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
from app.scraping.listing_filters import (
    category_is_wanted,
    is_worldwide_text,
    prefer_listing_card,
)

_DETAIL_RE = re.compile(r"^/giveaways/[a-z0-9\-]+/?$", re.IGNORECASE)
_LISTING_HINTS = (
    "/country/",
    "/category/",
    "/giveaways/",
    "/ending-soon",
)


class WorldFreePrizesAdapter:
    key = "world_free_prizes"

    def enrich(self, response: Any, *, page_url: str) -> PageEnrichment:
        path = urlparse(page_url).path or "/"
        is_detail = bool(_DETAIL_RE.match(path)) and path.rstrip("/") != "/giveaways"

        if not is_detail:
            return self._listing(response, page_url, path)

        title = first_css_text(response, ("h1", "title"))
        body = body_text(response)
        category = _labeled(body, "Prize category") or _labeled(body, "Category")
        end_date = _labeled(body, "Ends") or _labeled(body, "End date")
        prize = _labeled(body, "Prize")

        restriction = None
        if is_worldwide_text(body):
            restriction = "Worldwide"
        who = re.search(
            r"Who Can Enter\?\s*\n(.+?)(?:\n\n|\nHow to Enter|\nEligibility)",
            body,
            re.IGNORECASE | re.DOTALL,
        )
        if who:
            restriction = who.group(1).strip()[:400]
        elif m := re.search(
            r"(open (?:to|worldwide)[^\n]{0,120}|legal residents of[^\n]{0,120})",
            body,
            re.IGNORECASE,
        ):
            restriction = m.group(1).strip()[:300]

        entry_url = None
        for href, text in anchor_pairs(response):
            abs_url = absolute_url(page_url, href)
            if not abs_url:
                continue
            label = (text or "").lower()
            if any(
                k in label
                for k in (
                    "visit official",
                    "continue to official",
                    "official giveaway",
                    "enter",
                )
            ) and "worldfreeprizes.com" not in abs_url:
                entry_url = abs_url
                break
            if any(
                h in abs_url
                for h in ("gleam.io/", "sweepwidget.com/", "viralsweep.com/")
            ):
                entry_url = abs_url
                break

        meta: dict[str, Any] = {"category": category}
        if entry_url:
            identity = gleam_identity_from_url(entry_url) or sweepwidget_identity_from_url(
                entry_url
            )
            if identity:
                meta.update(identity)

        # Soft skip travel/crypto at adapter when category clear.
        skip = category_is_wanted(category or title or "") is False

        return PageEnrichment(
            title=title,
            prize=prize or title,
            end_date_text=end_date,
            entry_url=entry_url,
            restriction_text=restriction,
            excerpt=body[:3000] if body else None,
            skip_as_candidate=skip,
            meta=meta,
        )

    def _listing(self, response: Any, page_url: str, path: str) -> PageEnrichment:
        follow: list[str] = []
        # Prefer article cards when present.
        articles = response.css("article") or []
        if articles:
            for art in articles:
                text = (
                    art.get_all_text(separator=" ", strip=True)
                    if hasattr(art, "get_all_text")
                    else str(art)
                )
                geo = "Worldwide" if is_worldwide_text(text) or "/country/worldwide" in page_url else None
                if "/country/worldwide" in page_url:
                    geo = "Worldwide"
                if not prefer_listing_card(
                    geo_text=geo or text,
                    category_text=text,
                    require_worldwide="/country/worldwide" in page_url or bool(geo),
                ):
                    # On worldwide country page, still allow unknown category.
                    if "/country/worldwide" not in page_url:
                        continue
                    if category_is_wanted(text) is False:
                        continue
                for href in (
                    [str(x) for x in (art.css("a::attr(href)") or [])]
                    if hasattr(art, "css")
                    else []
                ):
                    abs_url = absolute_url(page_url, href)
                    if abs_url and _DETAIL_RE.match(urlparse(abs_url).path or ""):
                        follow.append(abs_url)
                        break
        else:
            for href in css_attr(response, 'a[href*="/giveaways/"]::attr(href)'):
                abs_url = absolute_url(page_url, href)
                if abs_url and _DETAIL_RE.match(urlparse(abs_url).path or ""):
                    follow.append(abs_url)

        return PageEnrichment(
            skip_as_candidate=True,
            follow_urls=dedupe_urls(follow) or None,
            meta={"hub": path, "follow_count": len(dedupe_urls(follow))},
        )


def _labeled(body: str, label: str) -> str | None:
    m = re.search(rf"{re.escape(label)}\s*\n\s*([^\n]+)", body, re.IGNORECASE)
    if m:
        return m.group(1).strip()[:300]
    m = re.search(rf"{re.escape(label)}\s*[:\|]\s*([^\n]+)", body, re.IGNORECASE)
    return m.group(1).strip()[:300] if m else None
