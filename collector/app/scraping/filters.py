"""URL filtering for crawl follow decisions."""

from __future__ import annotations

from urllib.parse import urlsplit

from app.urls import canonicalize_url, domain_from_url

_ASSET_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".css",
        ".js",
        ".mjs",
        ".map",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".webp",
        ".ico",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".mp4",
        ".mp3",
        ".avi",
        ".mov",
        ".zip",
        ".rar",
        ".gz",
        ".7z",
        ".xml",
        ".json",
        ".rss",
        ".atom",
    }
)

_BLOCKED_SCHEMES: frozenset[str] = frozenset(
    {"mailto", "javascript", "tel", "data", "blob", "file"}
)

_BLOCKED_HOST_HINTS: tuple[str, ...] = (
    "facebook.com",
    "fb.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "linkedin.com",
    "pinterest.com",
    "tiktok.com",
    "youtube.com",
    "youtu.be",
    "doubleclick.net",
    "googletagmanager.com",
    "google-analytics.com",
    "googleadservices.com",
)


def is_asset_url(url: str) -> bool:
    path = urlsplit(url).path.lower()
    for ext in _ASSET_EXTENSIONS:
        if path.endswith(ext):
            return True
    return False


def is_blocked_host(url: str) -> bool:
    try:
        host = domain_from_url(url)
    except ValueError:
        return True
    return any(host == h or host.endswith("." + h) for h in _BLOCKED_HOST_HINTS)


def should_follow_url(
    url: str,
    *,
    allowed_domains: set[str],
    base_domain: str | None = None,
) -> bool:
    """
    Return True if the crawler may enqueue this URL.

    Rejects non-http(s), assets, social/trackers, and off-domain links.
    """
    raw = (url or "").strip()
    if not raw or raw.startswith("#"):
        return False

    parts = urlsplit(raw)
    scheme = (parts.scheme or "").lower()
    if scheme in _BLOCKED_SCHEMES:
        return False
    if scheme and scheme not in {"http", "https"}:
        return False

    # Relative URLs are resolved by the spider before this filter; require absolute here.
    if not parts.netloc:
        return False

    if is_asset_url(raw):
        return False
    if is_blocked_host(raw):
        return False

    try:
        canonical = canonicalize_url(raw)
        host = domain_from_url(canonical)
    except ValueError:
        return False

    domains = {d.lower() for d in allowed_domains}
    if base_domain:
        domains.add(base_domain.lower())
    if not domains:
        return True
    return host in domains or any(host.endswith("." + d) for d in domains)


def normalize_follow_url(url: str) -> str | None:
    """Canonicalize a follow candidate; return None if invalid."""
    try:
        return canonicalize_url(url)
    except ValueError:
        return None
