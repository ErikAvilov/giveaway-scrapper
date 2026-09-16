"""SweepWidget campaign platform parser (not an aggregator).

Parses public directory/campaign HTML over ordinary HTTP.
Does not automate entry, CAPTCHA, or authentication.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

PLATFORM = "sweepwidget"

# https://sweepwidget.com/giveaways/101938-ew16zxym
# https://sweepwidget.com/c/101938-ew16zxym
_SW_PATH = re.compile(
    r"^/(?:giveaways|c)/(?P<id>\d+)(?:-(?P<slug>[A-Za-z0-9]+))?/?$",
    re.IGNORECASE,
)
_NON_CAMPAIGN = frozenset(
    {
        "",
        "blog",
        "docs",
        "signup",
        "login",
        "pricing",
        "features",
        "about",
        "contact",
    }
)


@dataclass(slots=True)
class SweepWidgetCampaign:
    platform_campaign_id: str
    title: str | None = None
    prize: str | None = None
    entry_url: str | None = None
    end_date_text: str | None = None
    start_date_text: str | None = None
    geo_restriction: str | None = None
    participant_count: str | None = None
    entry_count: str | None = None
    finished: bool = False
    excerpt: str | None = None

    def to_meta(self) -> dict[str, Any]:
        return {
            "platform": PLATFORM,
            "platform_campaign_id": self.platform_campaign_id,
            "entry_url": self.entry_url,
            "finished": self.finished,
            "participant_count": self.participant_count,
            "entry_count": self.entry_count,
        }


def is_sweepwidget_host(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower().removeprefix("www.")
    except (TypeError, ValueError, AttributeError):
        return False
    return host == "sweepwidget.com" or host.endswith(".sweepwidget.com")


def parse_sweepwidget_campaign_url(url: str) -> tuple[str | None, str | None]:
    """Return (campaign_id, slug) or (None, None)."""
    try:
        path = urlparse(url).path or "/"
    except (TypeError, ValueError, AttributeError):
        return None, None
    m = _SW_PATH.match(path)
    if not m:
        return None, None
    return m.group("id"), m.group("slug")


def sweepwidget_canonical_url(campaign_id: str, slug: str | None = None) -> str:
    if slug:
        return f"https://sweepwidget.com/giveaways/{campaign_id}-{slug}"
    return f"https://sweepwidget.com/giveaways/{campaign_id}"


def sweepwidget_identity_from_url(url: str) -> dict[str, Any] | None:
    cid, slug = parse_sweepwidget_campaign_url(url)
    if not cid:
        return None
    return {
        "platform": PLATFORM,
        "platform_campaign_id": cid,
        "entry_url": sweepwidget_canonical_url(cid, slug),
    }


def response_html(response: Any) -> str:
    html = getattr(response, "html_content", None) or getattr(response, "text", None)
    if isinstance(html, bytes):
        return html.decode("utf-8", errors="replace")
    if isinstance(html, str):
        return html
    body = getattr(response, "body", None)
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="replace")
    if isinstance(body, str):
        return body
    return str(response)


def parse_sweepwidget_campaign_html(
    html: str,
    *,
    page_url: str | None = None,
) -> SweepWidgetCampaign | None:
    cid = None
    slug = None
    if page_url:
        cid, slug = parse_sweepwidget_campaign_url(page_url)
    if not cid:
        m = re.search(r"/giveaways/(\d+)(?:-([A-Za-z0-9]+))?", html)
        if m:
            cid, slug = m.group(1), m.group(2)
    if not cid:
        return None

    title = _first_match(
        html,
        (
            r"<h1[^>]*>(.*?)</h1>",
            r'property="og:title"\s+content="([^"]+)"',
        ),
    )
    title = _strip_tags(title) if title else None

    prize = None
    prize_m = re.search(
        r"(?:Prizes|Prize)[^<]{0,40}</h2>\s*<p[^>]*>(.*?)</p>",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if prize_m:
        prize = _strip_tags(prize_m.group(1))[:400]
    if not prize:
        cash = re.search(r"(\$\d[\d,]*(?:\.\d+)?\s*(?:Cash|PayPal)?)", html, re.IGNORECASE)
        if cash:
            prize = cash.group(1)

    end_date = None
    for pat in (
        r"ENDED on ([A-Za-z]+ \d{1,2}, \d{4})",
        r"Ends?(?: on)?[:\s]+([A-Za-z]+ \d{1,2}, \d{4})",
        r"End(?:s| Date)[:\s]+([A-Za-z0-9 ,]+)",
    ):
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            end_date = m.group(1).strip()[:80]
            break

    start_date = None
    m = re.search(r"Start Time[^<]*</h2>\s*<p[^>]*>(.*?)</p>", html, re.IGNORECASE | re.DOTALL)
    if m:
        start_date = _strip_tags(m.group(1))[:80]

    finished = bool(re.search(r"\bENDED\b", html, re.IGNORECASE))

    geo = None
    for pat in (
        r"(Open to (?:residents )?worldwide)",
        r"(Open worldwide)",
        r"(Eligibility[:\s]+[^<\n]{5,120})",
        r"(Available (?:to|in) [^<\n]{5,120})",
        r"(US(?:A)? (?:residents? )?only)",
        r"(UK (?:residents? )?only)",
    ):
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            geo = _strip_tags(m.group(1))[:300]
            break

    participants = None
    m = re.search(r"([\d,]+)\s+participants?", html, re.IGNORECASE)
    if m:
        participants = m.group(1)

    entries = None
    m = re.search(r"([\d,]+)\s+entr(?:y|ies)", html, re.IGNORECASE)
    if m:
        entries = m.group(1)

    text = _strip_tags(html)
    excerpt = "\n".join(
        line.strip()
        for line in text.splitlines()
        if line.strip()
    )[:3000]

    return SweepWidgetCampaign(
        platform_campaign_id=cid,
        title=title,
        prize=prize,
        entry_url=sweepwidget_canonical_url(cid, slug),
        end_date_text=end_date,
        start_date_text=start_date,
        geo_restriction=geo,
        participant_count=participants,
        entry_count=entries,
        finished=finished,
        excerpt=excerpt,
    )


def _first_match(html: str, patterns: tuple[str, ...]) -> str | None:
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1)
    return None


def _strip_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
