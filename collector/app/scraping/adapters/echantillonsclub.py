"""ÉchantillonsClub adapter."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from app.scraping.adapters.base import (
    PageEnrichment,
    absolute_url,
    css_attr,
    first_css_text,
)

_DETAIL_RE = re.compile(r"/\d+-jeu-.+\.html$", re.IGNORECASE)
_LISTING_RE = re.compile(r"/concours(/page/\d+)?/?$", re.IGNORECASE)


class EchantillonsClubAdapter:
    key = "echantillonsclub"

    def enrich(self, response: Any, *, page_url: str) -> PageEnrichment:
        path = urlparse(page_url).path or "/"
        is_listing = bool(_LISTING_RE.search(path)) or path in {"", "/"}
        is_detail = bool(_DETAIL_RE.search(path))

        follow: list[str] = []
        for item in response.css(".item-list") or []:
            classes = ""
            if hasattr(item, "attrib"):
                classes = str(item.attrib.get("class") or "")
            if "iexpired" in classes.split():
                continue
            hrefs = item.css(
                "h2 a::attr(href), h3 a::attr(href), .post-thumbnail a::attr(href)"
            )
            for href in hrefs or []:
                abs_url = absolute_url(page_url, str(href))
                if abs_url and _DETAIL_RE.search(urlparse(abs_url).path or ""):
                    follow.append(abs_url)
        follow = _dedupe(follow)

        if is_listing and not is_detail:
            return PageEnrichment(skip_as_candidate=True, follow_urls=follow or None)

        title = first_css_text(response, ("h1", "h1.entry-title", ".entry-title", "title"))
        entry_url = None
        # /url/* is disallowed by robots.txt — store but never follow during crawl.
        for href in css_attr(response, 'a[href*="/url/"]::attr(href)'):
            entry_url = absolute_url(page_url, href)
            break
        if entry_url is None:
            for href, text in _anchor_pairs(response):
                label = (text or "").lower()
                if any(
                    t in label
                    for t in ("je joue", "je tente", "je profite", "participer")
                ):
                    abs_url = absolute_url(page_url, href)
                    if abs_url and "/url/" in abs_url:
                        entry_url = abs_url
                        break

        return PageEnrichment(
            title=title,
            entry_url=entry_url,
            skip_as_candidate=not is_detail,
            follow_urls=None,
            meta={"robots_note": "entry /url/* disallowed for fetch; stored only"},
        )


def _dedupe(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _anchor_pairs(response: Any) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for node in response.css("a") or []:
        href = str(node.attrib.get("href") or "") if hasattr(node, "attrib") else ""
        text = node.get_all_text(separator=" ", strip=True) if hasattr(node, "get_all_text") else ""
        pairs.append((href, text))
    return pairs
