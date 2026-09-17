"""Integration tests for giveaway upsert against Neon PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.content import compute_content_hash
from app.db.connection import connection
from app.db.repository import GiveawayRepository
from app.urls import canonicalize_url


@pytest.fixture
def db_conn(settings, migrated_db):
    with connection(settings) as conn:
        yield conn


@pytest.fixture
def unique_url() -> str:
    return f"https://test.giveaway.local/c/{uuid4()}?utm_source=pytest&slot=1"


def test_upsert_creates_then_updates_last_seen(db_conn, unique_url: str) -> None:
    repo = GiveawayRepository(db_conn)
    canonical = canonicalize_url(unique_url)
    try:
        first_seen = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        first = repo.upsert_from_crawl(
            url=unique_url,
            title="First title",
            raw_excerpt="excerpt A",
            content_hash=compute_content_hash("First title", None, "excerpt A"),
            seen_at=first_seen,
        )
        assert first.created is True
        assert first.content_hash_changed is True
        assert first.giveaway.canonical_url == canonical
        assert first.giveaway.domain == "test.giveaway.local"
        assert first.giveaway.title == "First title"
        assert first.giveaway.last_seen_at == first_seen

        # Simulate analysis already done
        analyzed = repo.save_analysis(
            first.giveaway.id,  # type: ignore[arg-type]
            analysis_json={"prize": "swag"},
            confidence=0.9,
        )
        assert analyzed.analyzed_at is not None
        assert analyzed.analysis_json == {"prize": "swag"}

        second_seen = first_seen + timedelta(hours=3)
        second = repo.upsert_from_crawl(
            url=unique_url + "&utm_campaign=again",
            title="Should not overwrite",
            raw_excerpt="excerpt A",
            content_hash=compute_content_hash("First title", None, "excerpt A"),
            seen_at=second_seen,
        )
        assert second.created is False
        assert second.content_hash_changed is False
        assert second.giveaway.id == first.giveaway.id
        assert second.giveaway.last_seen_at == second_seen
        assert second.giveaway.title == "First title"
        assert second.giveaway.analyzed_at is not None
        assert second.giveaway.analysis_json == {"prize": "swag"}
    finally:
        repo.delete_by_canonical_url(canonical)


def test_upsert_preserves_analysis_when_content_hash_changes(
    db_conn, unique_url: str
) -> None:
    repo = GiveawayRepository(db_conn)
    canonical = canonicalize_url(unique_url)
    try:
        first = repo.upsert_from_crawl(
            url=unique_url,
            title="Old",
            raw_excerpt="body-v1",
            content_hash="hash-v1",
        )
        analyzed = repo.save_analysis(
            first.giveaway.id,  # type: ignore[arg-type]
            analysis_json={"ok": True},
            status="active",
            confidence=0.8,
            eligible_france=True,
            france_eligibility="eligible",
            wanted_prize=True,
        )
        analyzed_at = analyzed.analyzed_at
        db_conn.execute(
            "UPDATE giveaways SET manual_status = %s WHERE id = %s",
            ("interested", first.giveaway.id),
        )

        second = repo.upsert_from_crawl(
            url=unique_url,
            title="New",
            raw_excerpt="body-v2",
            content_hash="hash-v2",
            eligible_france=None,
            france_eligibility=None,
            wanted_prize=None,
        )
        assert second.created is False
        assert second.content_hash_changed is True
        assert second.giveaway.title == "New"
        assert second.giveaway.raw_excerpt == "body-v2"
        assert second.giveaway.content_hash == "hash-v2"
        # Long-term memory: do not clear Gemini results on rediscovery.
        assert second.giveaway.analyzed_at == analyzed_at
        assert second.giveaway.analysis_json == {"ok": True}
        assert second.giveaway.confidence == 0.8
        assert second.giveaway.status.value == "active"
        assert second.giveaway.eligible_france is True
        assert second.giveaway.manual_status.value == "interested"

        needing = {str(g.canonical_url) for g in repo.list_needing_analysis(limit=500)}
        assert canonical not in needing
    finally:
        repo.delete_by_canonical_url(canonical)


def test_same_giveaway_with_different_tracking_collapses(db_conn) -> None:
    repo = GiveawayRepository(db_conn)
    token = uuid4()
    url_a = f"https://promo.example/win/{token}?utm_medium=email&code=KEEP"
    url_b = f"https://promo.example/win/{token}?fbclid=xyz&gclid=abc&code=KEEP"
    canonical = canonicalize_url(url_a)
    try:
        a = repo.upsert_from_crawl(url=url_a, title="A", content_hash="h1")
        b = repo.upsert_from_crawl(url=url_b, title="A", content_hash="h1")
        assert a.created is True
        assert b.created is False
        assert a.giveaway.id == b.giveaway.id
        assert str(a.giveaway.canonical_url) == canonical
        assert "code=KEEP" in canonical
        assert "utm_" not in canonical
        assert "fbclid" not in canonical
    finally:
        repo.delete_by_canonical_url(canonical)
