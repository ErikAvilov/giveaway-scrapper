"""Le Démon du Jeu adapter."""

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

_DETAIL_RE = re.compile(r"jeux-concours-.+\.html$", re.IGNORECASE)
_LISTING_HINTS = (
    "nouveaux-jeux-concours",
    "selection-concours",
    "jeux-concours-cloture",
)


class LeDemonDuJeuAdapter:
    key = "le_demon_du_jeu"

    def enrich(self, response: Any, *, page_url: str) -> PageEnrichment:
        path = (urlparse(page_url).path or "/").lstrip("/")
        is_detail = bool(_DETAIL_RE.search(path))
        is_listing = path in {"", "/"} or any(h in path for h in _LISTING_HINTS)

        follow: list[str] = []
        for href in css_attr(response, ".bloc-article a::attr(href)"):
            abs_url = absolute_url(page_url, href)
            if not abs_url:
                continue
            p = (urlparse(abs_url).path or "").lstrip("/")
            if _DETAIL_RE.search(p) or p.startswith("concours-"):
                follow.append(abs_url)
        follow = _dedupe(follow)

        if is_listing and not is_detail:
            return PageEnrichment(skip_as_candidate=True, follow_urls=follow or None)

        title = first_css_text(
            response,
            (".bloc-article-text-titre", ".bloc-article-titre", "h1", "title"),
        )
        entry_url = None
        for href, text in _anchor_pairs(response):
            label = (text or "").lower()
            href_l = href or ""
            if ("voir le concours" in label or "toconc.php" in href_l) and (
                "toconc" in href_l or "voir le concours" in label
            ):
                entry_url = absolute_url(page_url, href)
                if entry_url and "toconc" in entry_url:
                    break
        if entry_url is None:
            for href in css_attr(response, 'a[href*="toconc.php"]::attr(href)'):
                entry_url = absolute_url(page_url, href)
                break

        return PageEnrichment(
            title=title,
            entry_url=entry_url,
            skip_as_candidate=False,
            follow_urls=None,
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
