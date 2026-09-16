"""Online Competitions (UK) adapter."""

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
    first_css_text,
    same_registrable_host,
)

_DETAIL_RE = re.compile(r"^/competitions/[a-z0-9\-]+/?$", re.IGNORECASE)
_CLOSED = re.compile(r"this competition has closed", re.IGNORECASE)


class OnlineCompetitionAdapter:
    key = "online_competition"

    def enrich(self, response: Any, *, page_url: str) -> PageEnrichment:
        path = urlparse(page_url).path or "/"
        is_detail = bool(_DETAIL_RE.match(path))
        is_hub = path in {"", "/", "/competitions", "/competitions/"}

        follow: list[str] = []
        for href in css_attr(response, 'a[href*="/competitions/"]::attr(href)'):
            abs_url = absolute_url(page_url, href)
            if abs_url and _DETAIL_RE.match(urlparse(abs_url).path or ""):
                follow.append(abs_url)
        follow = dedupe_urls(follow)

        if is_hub or not is_detail:
            return PageEnrichment(skip_as_candidate=True, follow_urls=follow or None)

        title = first_css_text(response, ("h1", "title"))
        body = body_text(response)
        closed = bool(_CLOSED.search(body))

        prize = None
        m = re.search(r"The prize\n(.+?)(?:\nClosing date|\nWho can enter)", body, re.DOTALL)
        if m:
            prize = m.group(1).strip()[:500]

        closing = None
        m = re.search(r"Closing date\n(.+)", body)
        if m:
            closing = m.group(1).strip()[:120]

        restriction = None
        m = re.search(r"Who can enter\n(.+)", body)
        if m:
            restriction = m.group(1).strip()[:300]

        instructions = None
        m = re.search(r"How to enter\n(.+?)(?:\nEntry limit|\nGo to)", body, re.DOTALL)
        if m:
            instructions = m.group(1).strip()[:500]

        entry_method = None
        if "website entry" in body.lower():
            entry_method = "Website"
        em = first_css_text(response, (".oc-entry-method",))
        if em:
            entry_method = em

        entry_url = None
        terms_url = None
        for href, text in anchor_pairs(response):
            label = (text or "").lower().replace("\n", " ")
            abs_url = absolute_url(page_url, href)
            if not abs_url or same_registrable_host(abs_url, "onlinecompetition.co.uk"):
                continue
            if "original competition" in label or "go to the original" in label:
                entry_url = abs_url
            if "official terms" in label or "terms and conditions" in label:
                terms_url = abs_url

        organizer = None
        m = re.search(r"Promoted by ([^·\n]+)", body)
        if m:
            organizer = m.group(1).strip()[:200]

        return PageEnrichment(
            title=title,
            prize=prize,
            end_date_text=closing,
            entry_url=entry_url,
            terms_url=terms_url,
            organizer=organizer,
            restriction_text=restriction,
            entry_method_text=instructions or entry_method,
            excerpt=body[:3000] if body else None,
            skip_as_candidate=False,
            follow_urls=None,
            meta={
                "expired": closed,
                "free_hint": True,
                "purchase_required_text": "No purchase required" if "no purchase" in body.lower() else None,
            },
        )
