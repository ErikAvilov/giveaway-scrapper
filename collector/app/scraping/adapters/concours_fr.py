"""Concours.fr adapter."""

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

_WP_ASSET = re.compile(r"/wp-content|/wp-includes|/feed/?$", re.IGNORECASE)


class ConcoursFrAdapter:
    key = "concours_fr"

    def enrich(self, response: Any, *, page_url: str) -> PageEnrichment:
        path = urlparse(page_url).path or "/"
        is_home = path in {"", "/"}
        is_category = "/categorie-" in path or path.rstrip("/").endswith("/category")
        is_listing = is_home or is_category
        is_post = (
            not is_listing
            and path not in {"", "/"}
            and not _WP_ASSET.search(path)
            and path.count("/") >= 1
        )

        follow: list[str] = []
        for href in css_attr(response, "a.tpg-post-link::attr(href), .entry-title a::attr(href), article a::attr(href)"):
            abs_url = absolute_url(page_url, href)
            if (
                abs_url
                and same_registrable_host(abs_url, "concours.fr")
                and not _WP_ASSET.search(urlparse(abs_url).path or "")
                and "/categorie-" not in (urlparse(abs_url).path or "")
            ):
                follow.append(abs_url)
        follow = _dedupe(follow)

        if is_listing or not is_post:
            return PageEnrichment(skip_as_candidate=True, follow_urls=follow or None)

        title = first_css_text(response, ("h1.entry-title", ".entry-title", "h1", "title"))
        entry_url = None
        for href, text in _anchor_pairs(response):
            label = (text or "").strip().lower()
            if label in {"participer", "je participe", "participer !"} or label.startswith(
                "participer"
            ):
                abs_url = absolute_url(page_url, href)
                if abs_url and not same_registrable_host(abs_url, "concours.fr"):
                    entry_url = abs_url
                    break
                if abs_url and "instagram.com" in abs_url:
                    entry_url = abs_url
                    break

        return PageEnrichment(
            title=title,
            entry_url=entry_url,
            skip_as_candidate=not is_post,
            follow_urls=None if is_post else (follow or None),
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
