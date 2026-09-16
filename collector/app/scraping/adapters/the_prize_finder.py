"""The Prize Finder adapter (RSS hub → competition detail pages)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlparse

from app.scraping.adapters.base import (
    PageEnrichment,
    absolute_url,
    anchor_pairs,
    body_text,
    css_attr,
    dedupe_urls,
    first_css_text,
    same_registrable_host,
)

_DETAIL_RE = re.compile(r"^/competitions/[a-z0-9\-]+/?$", re.IGNORECASE)
_CATEGORY_BLOCK = re.compile(
    r"/(new-competitions|closing-soon|top-prizes|facebook-competitions|"
    r"twitter-competitions|instagram-competitions|blog-competitions|"
    r"tv-competitions|daily-entry-competitions)(?:/|$)",
    re.IGNORECASE,
)


def _response_bytes(response: Any) -> bytes:
    body = getattr(response, "body", None)
    if isinstance(body, bytes):
        return body
    if isinstance(body, str):
        return body.encode("utf-8", errors="replace")
    html = getattr(response, "html_content", None) or getattr(response, "text", None)
    if isinstance(html, bytes):
        return html
    if isinstance(html, str):
        return html.encode("utf-8", errors="replace")
    return b""


def _parse_rss_links(raw: bytes, page_url: str) -> list[str]:
    if b"<rss" not in raw[:2000].lower() and b"<item>" not in raw[:5000].lower():
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    links: list[str] = []
    for item in root.findall(".//item"):
        link = (item.findtext("link") or "").strip()
        if not link:
            continue
        abs_url = absolute_url(page_url, link)
        if abs_url and _DETAIL_RE.match(urlparse(abs_url).path or ""):
            links.append(abs_url)
    return dedupe_urls(links)


def _field_item(response: Any, field_name: str) -> str | None:
    # Drupal-ish: .field--name-field-X .field--item
    sel = f".field--name-{field_name} .field--item, .field--name-field-{field_name} .field--item"
    return first_css_text(response, (sel,))


class ThePrizeFinderAdapter:
    key = "the_prize_finder"

    def enrich(self, response: Any, *, page_url: str) -> PageEnrichment:
        path = urlparse(page_url).path or "/"
        raw = _response_bytes(response)
        rss_links = _parse_rss_links(raw, page_url)
        if rss_links or path.rstrip("/").endswith("rss.xml") or path.rstrip("/").endswith("/rss"):
            return PageEnrichment(
                skip_as_candidate=True,
                follow_urls=rss_links or None,
                meta={"hub": "rss"},
            )

        is_detail = bool(_DETAIL_RE.match(path)) and not _CATEGORY_BLOCK.search(path)
        # Category / search / listing pages
        if not is_detail:
            follow: list[str] = []
            prefer_worldwide = "worldwide" in page_url.lower() or "keys=worldwide" in page_url.lower()
            articles = response.css("article") or []
            if articles and prefer_worldwide:
                for art in articles:
                    text = (
                        art.get_all_text(separator=" ", strip=True)
                        if hasattr(art, "get_all_text")
                        else str(art)
                    )
                    # Only follow cards that look Worldwide when searching worldwide.
                    if "worldwide" not in text.lower():
                        continue
                    for href in (
                        [str(x) for x in (art.css('a[href*="/competitions/"]::attr(href)') or [])]
                        if hasattr(art, "css")
                        else []
                    ):
                        abs_url = absolute_url(page_url, href)
                        if not abs_url:
                            continue
                        p = urlparse(abs_url).path or ""
                        if _DETAIL_RE.match(p) and not _CATEGORY_BLOCK.search(p):
                            follow.append(abs_url)
                            break
            if not follow:
                for href in css_attr(response, 'a[href*="/competitions/"]::attr(href)'):
                    abs_url = absolute_url(page_url, href)
                    if not abs_url:
                        continue
                    p = urlparse(abs_url).path or ""
                    if _DETAIL_RE.match(p) and not _CATEGORY_BLOCK.search(p):
                        follow.append(abs_url)
            return PageEnrichment(
                skip_as_candidate=True,
                follow_urls=dedupe_urls(follow) or None,
                meta={"prefer_worldwide": prefer_worldwide},
            )

        title = first_css_text(response, ("h1", "h1.node-title", "title"))
        promoter = _field_item(response, "website-name") or first_css_text(
            response, (".field--name-website-name .field--item",)
        )
        closing = _field_item(response, "closing-date") or first_css_text(
            response,
            (
                ".field--name-website-name + .field .field--item",
                ".field--name-field-closing-date .field--item",
            ),
        )
        # Closing Date often uses a generic adjacent field — also scan labels.
        instructions = _field_item(response, "field-instructions") or _field_item(
            response, "instructions"
        )
        restriction = _field_item(response, "field-restriction") or _field_item(
            response, "restriction"
        )
        body = body_text(response)
        if not closing and "Closing Date:" in body:
            m = re.search(r"Closing Date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", body)
            if m:
                closing = m.group(1)
        if not instructions:
            m = re.search(r"Instructions\s*\n\s*(.+)", body)
            if m:
                instructions = m.group(1).strip()[:200]
        if not restriction:
            m = re.search(r"Restriction\s*\n\s*(.+)", body)
            if m:
                restriction = m.group(1).strip()[:300]

        entry_url = None
        for href, text in anchor_pairs(response):
            label = (text or "").lower()
            abs_url = absolute_url(page_url, href)
            if not abs_url:
                continue
            if "link-track" in abs_url and (
                "view competition" in label or title and title.lower() in label
            ):
                entry_url = abs_url
                break
        if entry_url is None:
            for href, _text in anchor_pairs(response):
                abs_url = absolute_url(page_url, href)
                if abs_url and "link-track" in abs_url and same_registrable_host(
                    abs_url, "theprizefinder.com"
                ):
                    entry_url = abs_url
                    break

        # Soft skip only when Restriction is explicit and not Worldwide/International.
        # Leave missing restriction for spider/Gemini (unknown ≠ eligible).
        skip = False
        if restriction:
            low = restriction.lower().strip()
            if (
                "worldwide" not in low
                and "international" not in low
                and re.search(
                    r"\b(uk|united kingdom|us|usa|united states|canada|australia)\b",
                    low,
                )
                and "france" not in low
            ):
                skip = True

        return PageEnrichment(
            title=title,
            end_date_text=closing,
            entry_url=entry_url,
            organizer=promoter,
            restriction_text=restriction,
            entry_method_text=instructions,
            excerpt=body[:3000] if body else None,
            skip_as_candidate=skip,
            follow_urls=None,
            meta={
                "entry_url_is_tracker": bool(entry_url and "link-track" in entry_url),
                "skip_reasons": ["restriction_not_worldwide"] if skip else [],
            },
        )
