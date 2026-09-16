"""Prize Runner (UK) adapter."""

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

_POST_RE = re.compile(r"^/\d{4}/\d{2}/[a-z0-9\-]+/?$", re.IGNORECASE)


class PrizeRunnerAdapter:
    key = "prize_runner"

    def enrich(self, response: Any, *, page_url: str) -> PageEnrichment:
        path = urlparse(page_url).path or "/"
        is_detail = bool(_POST_RE.match(path))
        is_home = path in {"", "/"}

        follow: list[str] = []
        for href in css_attr(
            response,
            ".pr-post-entry a::attr(href), .entry-title a::attr(href), article a::attr(href)",
        ):
            abs_url = absolute_url(page_url, href)
            if abs_url and _POST_RE.match(urlparse(abs_url).path or ""):
                follow.append(abs_url)
        follow = dedupe_urls(follow)

        if is_home or not is_detail:
            return PageEnrichment(skip_as_candidate=True, follow_urls=follow or None)

        title = first_css_text(response, ("h1.entry-title", "h1", ".entry-title", "title"))
        body = body_text(response)

        promoter = None
        m = re.search(r"Promoter\n(.+)", body)
        if m:
            promoter = m.group(1).strip()[:200]

        entry_method = None
        m = re.search(r"Entry Method\n(.+)", body)
        if m:
            entry_method = m.group(1).strip()[:120]

        closing = None
        m = re.search(r"Closing Date\n(.+)", body)
        if m:
            closing = m.group(1).strip()[:120]

        entry_url = None
        for href, text in anchor_pairs(response):
            label = (text or "").lower()
            abs_url = absolute_url(page_url, href)
            if not abs_url or same_registrable_host(abs_url, "prizerunner.co.uk"):
                continue
            if "enter this competition" in label or label.strip() in {"enter", "enter now"}:
                entry_url = abs_url
                break
        if entry_url is None:
            for href, text in anchor_pairs(response):
                label = (text or "").lower()
                abs_url = absolute_url(page_url, href)
                if abs_url and "enter" in label and not same_registrable_host(
                    abs_url, "prizerunner.co.uk"
                ):
                    entry_url = abs_url
                    break

        return PageEnrichment(
            title=title,
            end_date_text=closing,
            entry_url=entry_url,
            organizer=promoter,
            # Prize Runner is a UK free-comps directory; only set restriction when explicit.
            restriction_text=None,
            entry_method_text=entry_method,
            excerpt=body[:3000] if body else None,
            skip_as_candidate=False,
            follow_urls=None,
            meta={"free_hint": True},
        )
