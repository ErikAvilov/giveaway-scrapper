"""Tests for crawl depth and request deduplication helpers."""

from __future__ import annotations

from app.scraping.crawl_logic import can_go_deeper, next_depth, should_enqueue_canonical


def test_depth_default_two() -> None:
    assert can_go_deeper(0, 2)
    assert can_go_deeper(1, 2)
    assert not can_go_deeper(2, 2)
    assert next_depth(1, 2) == 2
    assert next_depth(2, 2) is None


def test_dedup_skips_seen_and_queued() -> None:
    seen = {"https://example.com/a"}
    queued: set[str] = set()
    assert should_enqueue_canonical(
        "https://example.com/b",
        seen=seen,
        queued=queued,
        max_pages=10,
        pages_fetched=1,
    )
    assert not should_enqueue_canonical(
        "https://example.com/a",
        seen=seen,
        queued=queued,
        max_pages=10,
        pages_fetched=1,
    )
    queued.add("https://example.com/c")
    assert not should_enqueue_canonical(
        "https://example.com/c",
        seen=seen,
        queued=queued,
        max_pages=10,
        pages_fetched=1,
    )


def test_dedup_respects_page_budget() -> None:
    assert not should_enqueue_canonical(
        "https://example.com/x",
        seen={"https://example.com/1", "https://example.com/2"},
        queued=set(),
        max_pages=2,
        pages_fetched=2,
    )
