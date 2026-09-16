"""GleamGiveaways.com aggregator — prefer Worldwide + wanted categories."""

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
from app.scraping.listing_filters import prefer_listing_card

_DETAIL_RE = re.compile(r"/giveaways/[a-z0-9\-]+/?$", re.IGNORECASE)
_SKIP_PATHS = (
    "/giveaways/platform/",
    "/giveaways/category/",
    "/category/",
    "/platforms/",
)

_WANTED_CATS = (
    "electronics",
    "gadget",
    "gaming",
    "home",
    "furniture",
    "appliance",
    "cash",
    "gift card",
    "tools",
)


class GleamGiveawaysAdapter:
    key = "gleam_giveaways"

    def enrich(self, response: Any, *, page_url: str) -> PageEnrichment:
        path = urlparse(page_url).path or "/"
        is_detail = bool(_DETAIL_RE.search(path)) and not any(
            s in path for s in _SKIP_PATHS
        )

        if not is_detail:
            return self._listing(response, page_url)

        title = first_css_text(response, ("h1", ".gg-card-title", "title"))
        body = body_text(response)
        eligible = _labeled_value(body, "Eligible") or _find_eligible_line(body)
        category = _labeled_value(body, "Category")
        end_date = _labeled_value(body, "End date") or _labeled_value(body, "Ends")
        prize = _labeled_value(body, "Grand Prize Value") or _find_prize(body)

        entry_url = None
        for href, text in anchor_pairs(response):
            label = (text or "").lower()
            abs_url = absolute_url(page_url, href)
            if not abs_url:
                continue
            if "enter" in label and not urlparse(abs_url).path.startswith("/giveaways/"):
                entry_url = abs_url
                break
            if any(
                h in abs_url
                for h in (
                    "gleam.io/",
                    "sweepwidget.com/",
                    "viralsweep.com/",
                    "wn.nr/",
                    "swee.ps/",
                )
            ):
                entry_url = abs_url
                break

        meta: dict[str, Any] = {"category": category, "eligible_badge": eligible}
        if entry_url:
            identity = gleam_identity_from_url(entry_url) or sweepwidget_identity_from_url(
                entry_url
            )
            if identity:
                meta.update(identity)

        # Listing-level geo preference already applied when following; still expose.
        return PageEnrichment(
            title=title,
            prize=prize,
            end_date_text=end_date,
            entry_url=entry_url,
            restriction_text=eligible,
            excerpt=body[:3000] if body else None,
            skip_as_candidate=False,
            meta=meta,
        )

    def _listing(self, response: Any, page_url: str) -> PageEnrichment:
        follow: list[str] = []
        cards = response.css(".gg-card") or []
        for card in cards:
            text = (
                card.get_all_text(separator=" ", strip=True)
                if hasattr(card, "get_all_text")
                else str(card)
            )
            geo = _card_geo(text)
            category = _card_category(text)
            title_nodes = card.css(".gg-card-title") if hasattr(card, "css") else []
            title = (
                title_nodes[0].get_all_text(strip=True)
                if title_nodes and hasattr(title_nodes[0], "get_all_text")
                else None
            )
            if not prefer_listing_card(
                geo_text=geo,
                category_text=category or text,
                title=title,
                require_worldwide=True,
            ):
                continue
            hrefs = []
            if hasattr(card, "css"):
                hrefs = [str(x) for x in (card.css("a::attr(href)") or [])]
            for href in hrefs:
                abs_url = absolute_url(page_url, href)
                if not abs_url:
                    continue
                p = urlparse(abs_url).path or ""
                if _DETAIL_RE.search(p) and not any(s in p for s in _SKIP_PATHS):
                    follow.append(abs_url)
                    break

        # Fallback: any giveaway detail links if card CSS missing.
        if not follow:
            for href in css_attr(response, 'a[href*="/giveaways/"]::attr(href)'):
                abs_url = absolute_url(page_url, href)
                if not abs_url:
                    continue
                p = urlparse(abs_url).path or ""
                if _DETAIL_RE.search(p) and not any(s in p for s in _SKIP_PATHS):
                    follow.append(abs_url)

        return PageEnrichment(
            skip_as_candidate=True,
            follow_urls=dedupe_urls(follow) or None,
            meta={"listing_filtered": True, "follow_count": len(dedupe_urls(follow))},
        )


def _card_geo(text: str) -> str | None:
    if "Worldwide" in text or "🌍" in text:
        return "Worldwide"
    m = re.search(
        r"(🇺🇸\s*US|🇬🇧\s*UK|🇨🇦\s*Canada|🇦🇺\s*Australia|\bUS\b|\bUK\b)",
        text,
    )
    return m.group(1) if m else None


def _card_category(text: str) -> str | None:
    for cat in _WANTED_CATS:
        if cat in text.lower():
            return cat
    m = re.search(
        r"(Electronics & Gadgets|Gaming|Home, Furniture & Appliances|"
        r"Cash & Gift Cards|Tools & Hardware|Travel & Leisure|Crypto)",
        text,
        re.IGNORECASE,
    )
    return m.group(1) if m else None


def _labeled_value(body: str, label: str) -> str | None:
    m = re.search(
        rf"{re.escape(label)}\s*\n\s*(.+)",
        body,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()[:300]
    m = re.search(rf"{re.escape(label)}\s*[:\|]\s*(.+)", body, re.IGNORECASE)
    if m:
        return m.group(1).strip().split("\n")[0][:300]
    return None


def _find_eligible_line(body: str) -> str | None:
    m = re.search(
        r"Eligible\s*(🌍\s*Worldwide|🇺🇸\s*US|🇬🇧\s*UK|[^\n]{2,40})",
        body,
        re.IGNORECASE,
    )
    return m.group(1).strip() if m else None


def _find_prize(body: str) -> str | None:
    m = re.search(r"\$[\d,]+(?:\s*[–-]\s*\$[\d,]+)?", body)
    return m.group(0) if m else None
