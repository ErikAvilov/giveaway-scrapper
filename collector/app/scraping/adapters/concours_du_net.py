"""Concours du Net adapter."""

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

_DETAIL_RE = re.compile(r"/jeu-concours-[a-z0-9\-]+", re.IGNORECASE)
_LISTING_RE = re.compile(
    r"/(nouveaux-concours|concours-[a-z0-9\-]+)(?:/|$|\?)",
    re.IGNORECASE,
)


class ConcoursDuNetAdapter:
    key = "concours_du_net"

    def enrich(self, response: Any, *, page_url: str) -> PageEnrichment:
        path = urlparse(page_url).path or "/"
        is_detail = bool(_DETAIL_RE.search(path))
        is_home = path in {"", "/"}

        follow: list[str] = []
        for href in css_attr(response, ".home-contest-card a::attr(href)"):
            abs_url = absolute_url(page_url, href)
            if abs_url and _DETAIL_RE.search(urlparse(abs_url).path or ""):
                follow.append(abs_url)
        # Dedup preserve order
        seen: set[str] = set()
        follow_unique = []
        for u in follow:
            if u not in seen:
                seen.add(u)
                follow_unique.append(u)

        if is_home or (not is_detail and _LISTING_RE.search(path)):
            return PageEnrichment(
                skip_as_candidate=True,
                follow_urls=follow_unique or None,
            )

        if not is_detail:
            return PageEnrichment(skip_as_candidate=False, follow_urls=follow_unique or None)

        title = first_css_text(
            response,
            ("h1", ".home-contest-title", "title"),
        )
        prize = first_css_text(
            response,
            (".home-contest-prize", "[class*='prize']", "h1"),
        )
        entry_url = None
        # Prefer the first "Participer" track link on the detail body.
        for href, text in _anchor_pairs(response):
            label = (text or "").lower()
            if "particip" in label and "track.php" in (href or ""):
                entry_url = absolute_url(page_url, href)
                break
        if entry_url is None:
            tracks = css_attr(response, 'a[href*="track.php"]::attr(href)')
            if tracks:
                entry_url = absolute_url(page_url, tracks[0])

        return PageEnrichment(
            title=title,
            prize=prize,
            entry_url=entry_url,
            skip_as_candidate=False,
            follow_urls=None,
        )


def _anchor_pairs(response: Any) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for node in response.css("a") or []:
        href = ""
        if hasattr(node, "attrib"):
            href = str(node.attrib.get("href") or "")
        text = ""
        if hasattr(node, "get_all_text"):
            text = node.get_all_text(separator=" ", strip=True)
        pairs.append((href, text))
    return pairs
