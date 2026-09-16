"""URL helpers: canonicalize giveaway links for deduplication."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Exact query keys stripped as tracking noise.
_TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "utm_reader",
        "utm_name",
        "utm_social",
        "utm_social-type",
        "fbclid",
        "gclid",
        "gclsrc",
        "dclid",
        "gbraid",
        "wbraid",
        "msclkid",
        "twclid",
        "li_fat_id",
        "mc_cid",
        "mc_eid",
        "_ga",
        "_gl",
        "_hsenc",
        "_hsmi",
        "yclid",
        "igshid",
        "ncid",
        "cmpid",
        "mkt_tok",
    }
)

# Prefixes for campaign/tracking params (utm_* already covered exactly above).
_TRACKING_PREFIXES: tuple[str, ...] = (
    "utm_",
    "mtm_",
    "pk_",
)


def canonicalize_url(url: str) -> str:
    """
    Normalize a URL for storage / uniqueness.

    Removes common tracking parameters (utm_*, fbclid, gclid, …) while keeping
    other query params that may identify the giveaway. Drops fragments, default
    ports, and normalizes scheme/host casing.
    """
    raw = url.strip()
    if not raw:
        raise ValueError("URL must not be empty")

    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"URL must be absolute with scheme and host: {url!r}")

    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported URL scheme: {scheme!r}")

    hostname = (parts.hostname or "").lower()
    if not hostname:
        raise ValueError(f"URL has no hostname: {url!r}")

    port = parts.port
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        netloc = f"{hostname}:{port}"
    else:
        netloc = hostname

    # Keep userinfo only if present (unusual for giveaway links).
    if parts.username:
        auth = parts.username
        if parts.password:
            auth = f"{auth}:{parts.password}"
        netloc = f"{auth}@{netloc}"

    path = parts.path or "/"
    # Collapse empty path to /
    if not path:
        path = "/"

    kept: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lower = key.lower()
        if lower in _TRACKING_PARAMS:
            continue
        if any(lower.startswith(prefix) for prefix in _TRACKING_PREFIXES):
            continue
        kept.append((key, value))

    # Stable order so the same logical URL maps to one canonical form.
    kept.sort(key=lambda kv: (kv[0].lower(), kv[1]))
    query = urlencode(kept, doseq=True)

    return urlunsplit((scheme, netloc, path, query, ""))


def domain_from_url(url: str) -> str:
    """Return the lowercase hostname for an absolute URL."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if not host:
        raise ValueError(f"URL has no hostname: {url!r}")
    return host
