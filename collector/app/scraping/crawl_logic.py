"""Pure helpers for crawl depth / request deduplication (easy to unit-test)."""

from __future__ import annotations


def can_go_deeper(depth: int, max_depth: int) -> bool:
    """Return True if links found at `depth` may still be followed."""
    return depth < max_depth


def next_depth(depth: int, max_depth: int) -> int | None:
    nxt = depth + 1
    if nxt > max_depth:
        return None
    return nxt


def should_enqueue_canonical(
    canonical_url: str,
    *,
    seen: set[str],
    queued: set[str],
    max_pages: int,
    pages_fetched: int,
) -> bool:
    """
    Dedup + budget gate before enqueueing a follow-up request.

    `seen` = already fetched; `queued` = already scheduled this run.
    """
    if pages_fetched >= max_pages:
        return False
    if canonical_url in seen or canonical_url in queued:
        return False
    return len(seen) + len(queued) < max_pages
