"""Source-specific listing/detail extraction adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urljoin, urlparse


@dataclass(slots=True)
class ChildCandidate:
    """Extra giveaway emitted from a listing page (one page → many candidates)."""

    canonical_url: str
    title: str | None = None
    prize: str | None = None
    entry_url: str | None = None
    excerpt: str | None = None
    end_date_text: str | None = None
    terms_url: str | None = None
    organizer: str | None = None
    restriction_text: str | None = None
    entry_method_text: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PageEnrichment:
    """Optional fields extracted from a crawled page."""

    title: str | None = None
    prize: str | None = None
    end_date_text: str | None = None
    entry_url: str | None = None
    terms_url: str | None = None
    organizer: str | None = None
    restriction_text: str | None = None
    entry_method_text: str | None = None
    excerpt: str | None = None
    # When True, do not emit this page as a giveaway candidate (hub/listing).
    skip_as_candidate: bool = False
    # Prefer these same-domain URLs when following links (None = use generic anchors).
    follow_urls: list[str] | None = None
    child_candidates: list[ChildCandidate] | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class SourceAdapter(Protocol):
    """Lightweight per-site parsing; keep each adapter self-contained."""

    key: str

    def enrich(self, response: Any, *, page_url: str) -> PageEnrichment: ...


def absolute_url(base: str, href: str | None) -> str | None:
    if not href:
        return None
    href = href.strip()
    if not href or href.startswith(("#", "javascript:", "mailto:")):
        return None
    return urljoin(base, href)


def same_registrable_host(url: str, host: str) -> bool:
    try:
        netloc = urlparse(url).netloc.lower().removeprefix("www.")
        host_n = host.lower().removeprefix("www.")
        return netloc == host_n or netloc.endswith("." + host_n)
    except (TypeError, ValueError, AttributeError):
        return False


def first_css_text(response: Any, selectors: tuple[str, ...]) -> str | None:
    for sel in selectors:
        nodes = response.css(sel)
        if not nodes:
            continue
        node = nodes[0]
        if hasattr(node, "get_all_text"):
            text = node.get_all_text(separator=" ", strip=True)
        else:
            text = str(node).strip()
        if text:
            return text[:500]
    return None


def css_attr(response: Any, selector: str) -> list[str]:
    try:
        values = response.css(selector)
    except (TypeError, ValueError, AttributeError):
        return []
    out: list[str] = []
    for value in values or []:
        text = str(value).strip()
        if text:
            out.append(text)
    return out


def anchor_pairs(response: Any) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for node in response.css("a") or []:
        href = ""
        if hasattr(node, "attrib"):
            href = str(node.attrib.get("href") or "")
        text = ""
        if hasattr(node, "get_all_text"):
            text = node.get_all_text(separator=" ", strip=True)
        pairs.append((href, text))
    return pairs


def body_text(response: Any, *, max_chars: int = 8000) -> str:
    nodes = response.css("body")
    if not nodes:
        return ""
    node = nodes[0]
    if hasattr(node, "get_all_text"):
        return node.get_all_text(separator="\n", strip=True)[:max_chars]
    return str(node)[:max_chars]


def dl_facts(response: Any) -> dict[str, str]:
    """Map <dt> → <dd> text for Giveario-style fact lists."""
    facts: dict[str, str] = {}
    for dt in response.css("dt") or []:
        key = (
            dt.get_all_text(separator=" ", strip=True)
            if hasattr(dt, "get_all_text")
            else str(dt).strip()
        )
        dd = None
        if hasattr(dt, "css"):
            # sibling dd via xpath-ish: next element — fall back to parent scan
            pass
        # Prefer paired structure under same parent
        parent = getattr(dt, "parent", None)
        if parent is not None and hasattr(parent, "css"):
            dds = parent.css("dd")
            if dds:
                dd = dds[0]
        if dd is None:
            continue
        val = (
            dd.get_all_text(separator=" ", strip=True)
            if hasattr(dd, "get_all_text")
            else str(dd).strip()
        )
        if key and val:
            facts[key.strip().lower()] = val[:500]
    # Also walk fact-item blocks
    for item in response.css(".fact-item") or []:
        dts = item.css("dt")
        dds = item.css("dd")
        if not dts or not dds:
            continue
        key = dts[0].get_all_text(separator=" ", strip=True).strip().lower()
        val = dds[0].get_all_text(separator=" ", strip=True)
        if key and val:
            facts[key] = val[:500]
    return facts


def dedupe_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out
