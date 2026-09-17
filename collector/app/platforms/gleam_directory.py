"""Parse Gleam.io public giveaway directory listing HTML."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from typing import Any
from urllib.parse import urljoin

from app.platforms.gleam import (
    canonicalize_gleam_directory_list_url,
    gleam_canonical_url,
    gleam_directory_detail_url,
    parse_gleam_directory_detail_url,
)

# Card block: detail link + title (directory listing).
_CARD_BLOCK = re.compile(
    r"""<a[^>]+href=["'](?P<href>/giveaways/[A-Za-z0-9]{4,12})["'][^>]*>
        (?P<body>.*?)
        </a>""",
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)

_TITLE = re.compile(
    r'class=["\']preview-tile__title["\'][^>]*>\s*(?P<title>[^<]+)\s*<',
    re.IGNORECASE,
)
_TIME_LEFT = re.compile(
    r"(\d+\s+(?:day|days|month|months|hour|hours)\s+left)",
    re.IGNORECASE,
)
_SPONSOR = re.compile(
    r'preview-tile__focusable-sponsor["\'][^>]*>\s*(?P<span>[^<]+)',
    re.IGNORECASE,
)
_IMG = re.compile(
    r"""(?:srcset|src)=["'](?P<src>https?://[^"'\s]+)["']""",
    re.IGNORECASE,
)

_PRIORITY_PRIZE = re.compile(
    r"\b(?:ps5|playstation|xbox|nintendo|steam\s*deck|gaming\s*pc|\bpc\b|gpu|rtx|"
    r"radeon|monitor|oled|macbook|laptop|smartphone|iphone|airpods?|headphones?|"
    r"\btv\b|e-?bike|\bbike\b|kitchenaid|appliance|cash|gift\s*card)\b",
    re.IGNORECASE,
)


@dataclass(slots=True, frozen=True)
class GleamDirectoryCard:
    directory_id: str
    detail_url: str
    title: str | None = None
    organizer: str | None = None
    time_left: str | None = None
    image_url: str | None = None
    priority_prize_hint: bool = False


def extract_directory_cards(html: str, *, page_url: str = "https://gleam.io/giveaways") -> list[GleamDirectoryCard]:
    """Extract giveaway cards from directory listing HTML (whitelist IDs only)."""
    cards: list[GleamDirectoryCard] = []
    seen: set[str] = set()
    for match in _CARD_BLOCK.finditer(html or ""):
        href = match.group("href")
        abs_url = urljoin(page_url, href)
        directory_id = parse_gleam_directory_detail_url(abs_url)
        if not directory_id or directory_id in seen:
            continue
        body = match.group("body") or ""
        # Brand/sponsor-only tiles link to /giveaways/by/... — already excluded by parser.
        title_m = _TITLE.search(body)
        title = unescape(title_m.group("title")).strip() if title_m else None
        if not title:
            # Skip bare image/nav anchors without a card title.
            continue
        time_m = _TIME_LEFT.search(body)
        sponsor_m = _SPONSOR.search(body)
        organizer = None
        if sponsor_m:
            organizer = unescape(sponsor_m.group("span")).strip()
            organizer = re.sub(r"^by\s+", "", organizer, flags=re.IGNORECASE).strip() or None
        img_m = _IMG.search(body)
        image_url = img_m.group("src") if img_m else None
        seen.add(directory_id)
        cards.append(
            GleamDirectoryCard(
                directory_id=directory_id,
                detail_url=gleam_directory_detail_url(directory_id),
                title=title,
                organizer=organizer,
                time_left=time_m.group(1) if time_m else None,
                image_url=image_url,
                priority_prize_hint=bool(title and _PRIORITY_PRIZE.search(title)),
            )
        )
    # Stable order: priority prize hints first, then original order.
    cards.sort(key=lambda c: (0 if c.priority_prize_hint else 1))
    return cards


def extract_directory_pagination_urls(
    html: str,
    *,
    page_url: str = "https://gleam.io/giveaways",
    max_pages: int = 5,
) -> list[str]:
    """
    Collect canonical useful sort/page links from listing HTML.

    Bounded by max_pages total listing URLs (including current sorts' pages).
    """
    hrefs = re.findall(r"""href=["']([^"']*giveaways[^"']*)["']""", html or "", re.IGNORECASE)
    found: list[str] = []
    seen: set[str] = set()
    for href in hrefs:
        abs_url = urljoin(page_url, unescape(href.replace("&amp;", "&")))
        canonical = canonicalize_gleam_directory_list_url(abs_url)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        found.append(canonical)
    # Prefer popular + newest + ending + odds page 1, then p=2.. 
    def _rank(u: str) -> tuple[int, int]:
        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(u).query)
        sort = (qs.get("s") or [""])[0]
        page = int((qs.get("p") or ["1"])[0] or 1)
        sort_rank = {"": 0, "n": 1, "e": 2, "s": 3}.get(sort, 9)
        return (sort_rank, page)

    found.sort(key=_rank)
    return found[: max(0, max_pages)]


def directory_follow_plan(
    html: str,
    *,
    page_url: str,
    max_listing_pages: int = 5,
) -> dict[str, Any]:
    """Cards + pagination follow set for the Gleam directory adapter.

    Follows classic campaign URLs (``/<id>/x``) so campaign parsing can happen
    without an extra shell hop, while still reporting ``/giveaways/<id>`` links
    as the discovered directory identities.
    """
    cards = extract_directory_cards(html, page_url=page_url)
    pages = extract_directory_pagination_urls(
        html, page_url=page_url, max_pages=max_listing_pages
    )
    current = canonicalize_gleam_directory_list_url(page_url)
    detail_urls = [c.detail_url for c in cards]
    # Prefer parseable classic pages (same stable campaign id as /giveaways/<id>).
    classic_urls = [gleam_canonical_url(c.directory_id, "x") for c in cards]
    follow = list(
        dict.fromkeys([*classic_urls, *[p for p in pages if p != current]])
    )
    return {
        "cards": cards,
        "detail_urls": detail_urls,
        "classic_follow_urls": classic_urls,
        "listing_urls": pages,
        "follow_urls": follow,
        "giveaway_links_discovered": len(cards),
    }
