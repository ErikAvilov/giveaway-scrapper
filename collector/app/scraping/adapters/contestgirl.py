"""ContestGirl adapter — listing cards emit child candidates (no detail crawl)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from app.platforms.gleam import gleam_identity_from_url
from app.scraping.adapters.base import (
    ChildCandidate,
    PageEnrichment,
    absolute_url,
    anchor_pairs,
    body_text,
)

# ContestGirl obfuscates vowels in outbound URLs: !!2=i !!3=e !!4=r !!5=a
_VOWEL_MAP = {"!!2": "i", "!!3": "e", "!!4": "r", "!!5": "a"}
_CARD_SPLIT = re.compile(r"\n(?=[A-Z][^\n]{0,80}--[^\n]+)")


def decode_contestgirl_url(obfuscated: str) -> str:
    out = unquote(obfuscated)
    for token, ch in _VOWEL_MAP.items():
        out = out.replace(token, ch)
    return out


def entry_url_from_counthits(href: str) -> str | None:
    """Extract organizer URL from /sweepstakes/countHits.pl?chu=... without fetching it."""
    if "countHits.pl" not in href and "chu=" not in href:
        return None
    parsed = urlparse(href)
    qs = parse_qs(parsed.query)
    chu = (qs.get("chu") or [None])[0]
    if not chu:
        return None
    decoded = decode_contestgirl_url(chu)
    if decoded.startswith("http"):
        return decoded
    return None


def _item_id_from_href(href: str) -> str | None:
    parsed = urlparse(href)
    qs = parse_qs(parsed.query)
    for key in ("chi", "i", "ix"):
        vals = qs.get(key)
        if vals and vals[0].isdigit():
            return vals[0]
    m = re.search(r"[?&](?:chi|i|ix)=(\d+)", href)
    return m.group(1) if m else None


class ContestGirlAdapter:
    key = "contestgirl"

    def enrich(self, response: Any, *, page_url: str) -> PageEnrichment:
        path = urlparse(page_url).path or "/"
        # Listing scripts under /contests/ — never fetch /sweepstakes/ (robots Disallow).
        if "/sweepstakes/" in path:
            return PageEnrichment(skip_as_candidate=True, follow_urls=None, meta={"blocked_path": True})

        is_listing = "contests.pl" in path or path.rstrip("/").endswith("/contests")
        if not is_listing and path not in {"", "/"}:
            # comment pages etc. — not used as primary discovery
            return PageEnrichment(skip_as_candidate=True, follow_urls=None)

        children: list[ChildCandidate] = []
        seen_ids: set[str] = set()

        for href, text in anchor_pairs(response):
            if "countHits.pl" not in (href or ""):
                continue
            abs_hit = absolute_url(page_url, href) or href
            item_id = _item_id_from_href(abs_hit)
            if not item_id or item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            entry = entry_url_from_counthits(abs_hit)
            title = (text or "").strip() or None
            canonical = absolute_url(
                page_url, f"/contests/comment.pl?i={item_id}"
            ) or f"https://www.contestgirl.com/contests/comment.pl?i={item_id}"
            children.append(
                ChildCandidate(
                    canonical_url=canonical,
                    title=title,
                    entry_url=entry,
                    meta=_child_meta(item_id, entry),
                )
            )

        # Enrich children with nearby listing text when possible.
        body = body_text(response, max_chars=20000)
        by_title = { (c.title or "").lower(): c for c in children if c.title }
        for block in _CARD_SPLIT.split(body):
            lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
            if not lines:
                continue
            head = lines[0]
            key = head.lower()
            child = by_title.get(key)
            if child is None:
                continue
            excerpt = "\n".join(lines[:12])
            child.excerpt = excerpt[:1500]
            for ln in lines:
                if ln.lower().startswith("end date:"):
                    child.end_date_text = ln.split(":", 1)[1].strip()
                if ln.lower().startswith("restrictions:"):
                    child.restriction_text = ln.split(":", 1)[1].strip()
            # Prize-ish first descriptive line after title
            for ln in lines[1:]:
                if ln.lower().startswith("enter for a chance"):
                    child.prize = ln[:400]
                    break

        # Follow pagination lightly (same listing script).
        follow: list[str] = []
        for href, text in anchor_pairs(response):
            label = (text or "").lower()
            if "contests.pl" in (href or "") and (
                label in {"next >>", "next"} or label.isdigit()
            ):
                abs_url = absolute_url(page_url, href)
                if abs_url and "/sweepstakes/" not in abs_url:
                    follow.append(abs_url)

        return PageEnrichment(
            skip_as_candidate=True,
            follow_urls=dedupe_follow(follow) or None,
            child_candidates=children or None,
            meta={"listing_cards": len(children)},
        )


def dedupe_follow(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _child_meta(item_id: str, entry_url: str | None) -> dict:
    meta: dict = {"contestgirl_id": item_id}
    if entry_url:
        identity = gleam_identity_from_url(entry_url)
        if identity:
            meta.update(identity)
    return meta
