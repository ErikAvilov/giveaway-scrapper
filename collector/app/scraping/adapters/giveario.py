"""Giveario adapter (shared for all country listing pages)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from app.scraping.adapters.base import (
    PageEnrichment,
    absolute_url,
    anchor_pairs,
    body_text,
    css_attr,
    dedupe_urls,
    dl_facts,
    first_css_text,
    same_registrable_host,
)

_DETAIL_RE = re.compile(r"^/en/giveaways/[a-z0-9\-]+/?$", re.IGNORECASE)
_COUNTRY_RE = re.compile(r"^/en/countries/[a-z0-9\-]+/?$", re.IGNORECASE)


class GivearioAdapter:
    key = "giveario"

    def enrich(self, response: Any, *, page_url: str) -> PageEnrichment:
        path = urlparse(page_url).path or "/"
        is_detail = bool(_DETAIL_RE.match(path))
        is_country = bool(_COUNTRY_RE.match(path))
        is_home = path in {"", "/", "/en", "/en/"}

        follow: list[str] = []
        for href in css_attr(response, 'a[href*="/en/giveaways/"]::attr(href)'):
            abs_url = absolute_url(page_url, href)
            if abs_url and _DETAIL_RE.match(urlparse(abs_url).path or ""):
                follow.append(abs_url)
        follow = dedupe_urls(follow)

        if is_home or is_country or not is_detail:
            return PageEnrichment(
                skip_as_candidate=True,
                follow_urls=follow or None,
            )

        facts = dl_facts(response)
        title = first_css_text(response, ("h1", "title"))
        prize = facts.get("prize")
        end_date = facts.get("deadline") or facts.get("ends")
        restriction = facts.get("open to") or facts.get("available in")
        purchase = facts.get("purchase required")
        organizer = facts.get("organizer")

        entry_url = None
        terms_url = None
        for href, text in anchor_pairs(response):
            label = (text or "").lower()
            abs_url = absolute_url(page_url, href)
            if not abs_url or same_registrable_host(abs_url, "giveario.com"):
                continue
            if "official promotion" in label or label.strip() in {"enter", "enter now"}:
                entry_url = abs_url
            if "official rules" in label or "terms" in label:
                terms_url = abs_url
        if entry_url is None:
            for href, text in anchor_pairs(response):
                label = (text or "").lower()
                abs_url = absolute_url(page_url, href)
                if abs_url and "visit the official" in label:
                    entry_url = abs_url
                    break

        how = ""
        body = body_text(response)
        if "how to enter" in body.lower():
            idx = body.lower().index("how to enter")
            how = body[idx : idx + 600]

        return PageEnrichment(
            title=title,
            prize=prize,
            end_date_text=end_date,
            entry_url=entry_url,
            terms_url=terms_url,
            organizer=organizer,
            restriction_text=restriction,
            entry_method_text=how or None,
            excerpt=body[:3000] if body else None,
            skip_as_candidate=False,
            follow_urls=None,
            meta={
                "purchase_required_text": purchase,
                "source_region": restriction,
            },
        )
