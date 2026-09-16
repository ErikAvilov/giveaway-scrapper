"""Mes Échantillons Gratuits adapter."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from app.scraping.adapters.base import (
    PageEnrichment,
    absolute_url,
    css_attr,
    first_css_text,
    same_registrable_host,
)

_DETAIL_RE = re.compile(r"/jeux-concours/[^/]+/?$", re.IGNORECASE)
_CATEGORY_EXACT = re.compile(
    r"/jeux-concours/(page/\d+/)?$",
    re.IGNORECASE,
)
_CATEGORY_SECTIONS = re.compile(
    r"/jeux-concours/(produits-beaute|bebe|parfums|nourriture|voyages|"
    r"bijoux-accessoires|culture|mode|argent|maisons)/?$",
    re.IGNORECASE,
)


class MesEchantillonsGratuitsAdapter:
    key = "mes_echantillons_gratuits"

    def enrich(self, response: Any, *, page_url: str) -> PageEnrichment:
        path = urlparse(page_url).path or "/"
        is_listing = bool(_CATEGORY_EXACT.match(path) or _CATEGORY_SECTIONS.search(path))
        is_detail = bool(_DETAIL_RE.search(path)) and not is_listing

        follow: list[str] = []
        for href in css_attr(response, ".col_item a::attr(href), .qeg-card-heading a::attr(href)"):
            abs_url = absolute_url(page_url, href)
            if not abs_url:
                continue
            p = urlparse(abs_url).path or ""
            if _DETAIL_RE.search(p) and not _CATEGORY_EXACT.match(p) and not _CATEGORY_SECTIONS.search(p):
                follow.append(abs_url)
        follow = _dedupe(follow)

        if is_listing or path.rstrip("/").endswith("/jeux-concours"):
            return PageEnrichment(skip_as_candidate=True, follow_urls=follow or None)

        title = first_css_text(
            response,
            ("h1", ".qeg-card-heading", ".entry-title", "title"),
        )
        # Clean noisy card titles that include meta prefixes.
        if title and title.lower().startswith("concours"):
            parts = title.split("\n")
            title = max(parts, key=len).strip() if parts else title

        entry_url = None
        for href, text in _anchor_pairs(response):
            label = (text or "").strip().lower()
            if any(
                token in label
                for token in ("j'en profite", "jen profite", "je participe", "participer")
            ):
                abs_url = absolute_url(page_url, href)
                if abs_url and not same_registrable_host(abs_url, "mesechantillonsgratuits.fr"):
                    entry_url = abs_url
                    break

        return PageEnrichment(
            title=title,
            entry_url=entry_url,
            skip_as_candidate=not is_detail,
            follow_urls=None if is_detail else (follow or None),
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
