"""Lifecycle / long-term memory regression tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.content import compute_content_hash
from app.db.connection import connection
from app.db.repository import GiveawayRepository
from app.gemini.service import SkipReason, should_skip_analysis
from app.models.giveaway import GiveawayStatus, ManualStatus
from app.urls import canonicalize_url


@pytest.fixture
def db_conn(settings, migrated_db):
    with connection(settings) as conn:
        yield conn


def _seed_source(conn, name: str | None = None) -> object:
    from app.db.repository import SourceRepository

    repo = SourceRepository(conn)
    token = uuid4().hex[:8]
    return repo.create(
        name=name or f"src-{token}",
        base_url=f"https://src-{token}.example/",
        source_type="other",
        enabled=True,
        crawl_interval_minutes=60,
    )


def test_rediscovery_preserves_analyzed_at_and_manual_status(db_conn) -> None:
    repo = GiveawayRepository(db_conn)
    url = f"https://lifecycle.test/ps5/{uuid4()}"
    canonical = canonicalize_url(url)
    try:
        first = repo.upsert_from_crawl(
            url=url,
            title="Win a PS5",
            raw_excerpt="body-v1",
            content_hash="hash-v1",
            eligible_france=True,
            france_eligibility="eligible",
            wanted_prize=True,
            entry_acceptable=True,
        )
        analyzed = repo.save_analysis(
            first.giveaway.id,  # type: ignore[arg-type]
            analysis_json={"prize": "PS5"},
            status=GiveawayStatus.ACTIVE,
            confidence=0.95,
            eligible_france=True,
            france_eligibility="eligible",
            wanted_prize=True,
            entry_acceptable=True,
        )
        analyzed_at = analyzed.analyzed_at
        assert analyzed_at is not None

        db_conn.execute(
            "UPDATE giveaways SET manual_status = %s WHERE id = %s",
            ("entered", first.giveaway.id),
        )
        db_conn.commit()

        later = datetime.now(UTC)
        second = repo.upsert_from_crawl(
            url=url,
            title="Win a PS5 — updated nav text",
            raw_excerpt="body-v2-different",
            content_hash="hash-v2",
            # Weaker rediscovery must not wipe confirmed FR eligibility
            eligible_france=None,
            france_eligibility=None,
            wanted_prize=None,
            entry_acceptable=None,
            seen_at=later,
        )
        assert second.created is False
        assert second.content_hash_changed is True
        assert second.giveaway.id == first.giveaway.id
        assert second.giveaway.last_seen_at == later
        assert second.giveaway.analyzed_at == analyzed_at
        assert second.giveaway.analysis_json == {"prize": "PS5"}
        assert second.giveaway.manual_status == ManualStatus.ENTERED
        assert second.giveaway.status == GiveawayStatus.ACTIVE
        assert second.giveaway.eligible_france is True
        assert second.giveaway.france_eligibility == "eligible"
        assert second.giveaway.wanted_prize is True
        assert second.giveaway.entry_acceptable is True
        assert second.giveaway.title == "Win a PS5 — updated nav text"
        assert second.giveaway.content_hash == "hash-v2"

        needing = {str(g.id) for g in repo.list_needing_analysis(limit=500)}
        assert str(first.giveaway.id) not in needing
    finally:
        repo.delete_by_canonical_url(canonical)


def test_rediscovered_ignored_stays_ignored(db_conn) -> None:
    repo = GiveawayRepository(db_conn)
    url = f"https://lifecycle.test/ignored/{uuid4()}"
    canonical = canonicalize_url(url)
    try:
        first = repo.upsert_from_crawl(url=url, title="X", content_hash="h1")
        repo.save_analysis(
            first.giveaway.id,  # type: ignore[arg-type]
            analysis_json={"ok": True},
            status=GiveawayStatus.ACTIVE,
            confidence=0.8,
        )
        db_conn.execute(
            "UPDATE giveaways SET manual_status = %s WHERE id = %s",
            ("ignored", first.giveaway.id),
        )
        second = repo.upsert_from_crawl(
            url=url, title="X2", content_hash="h2", raw_excerpt="changed"
        )
        assert second.giveaway.manual_status == ManualStatus.IGNORED
        assert second.giveaway.analyzed_at is not None
    finally:
        repo.delete_by_canonical_url(canonical)


def test_platform_campaign_dedup_one_logical_giveaway(db_conn) -> None:
    repo = GiveawayRepository(db_conn)
    token = uuid4().hex[:10]
    url_a = f"https://aggregator-a.example/g/{token}"
    url_b = f"https://aggregator-b.example/listing/{token}"
    campaign = f"camp-{token}"
    try:
        a = repo.upsert_from_crawl(
            url=url_a,
            title="Gleam PS5",
            content_hash="h1",
            platform="gleam",
            platform_campaign_id=campaign,
            entry_url=f"https://gleam.io/{campaign}/win",
        )
        b = repo.upsert_from_crawl(
            url=url_b,
            title="Same Gleam elsewhere",
            content_hash="h2",
            platform="gleam",
            platform_campaign_id=campaign,
            entry_url=f"https://gleam.io/{campaign}/win",
        )
        assert a.created is True
        assert b.created is False
        assert a.giveaway.id == b.giveaway.id
        assert b.giveaway.platform_campaign_id == campaign
    finally:
        repo.delete_by_canonical_url(canonicalize_url(url_a))


def test_strong_entry_url_dedup_across_aggregators(db_conn) -> None:
    repo = GiveawayRepository(db_conn)
    token = uuid4().hex[:10]
    entry = f"https://gleam.io/{token}/prize"
    url_a = f"https://cdn1.example/post/{token}"
    url_b = f"https://cdn2.example/article/{token}"
    try:
        a = repo.upsert_from_crawl(
            url=url_a,
            title="A",
            content_hash="h1",
            entry_url=entry,
            platform="gleam",
            platform_campaign_id=token,
        )
        b = repo.upsert_from_crawl(
            url=url_b,
            title="B",
            content_hash="h2",
            entry_url=entry,
        )
        assert a.created is True
        assert b.created is False
        assert a.giveaway.id == b.giveaway.id
    finally:
        repo.delete_by_canonical_url(canonicalize_url(url_a))


def test_multi_source_provenance(db_conn) -> None:
    repo = GiveawayRepository(db_conn)
    src_a = _seed_source(db_conn, "Alpha")
    src_b = _seed_source(db_conn, "Beta")
    db_conn.commit()
    url = f"https://lifecycle.test/multi/{uuid4()}"
    canonical = canonicalize_url(url)
    try:
        first = repo.upsert_from_crawl(
            url=url,
            source_id=src_a.id,
            title="Multi",
            content_hash="h1",
        )
        second = repo.upsert_from_crawl(
            url=url,
            source_id=src_b.id,
            title="Multi",
            content_hash="h1",
        )
        assert first.giveaway.id == second.giveaway.id
        # Primary source stays the first one.
        assert second.giveaway.source_id == src_a.id
        sources = repo.list_giveaway_sources(first.giveaway.id)  # type: ignore[arg-type]
        ids = {str(r["source_id"]) for r in sources}
        assert str(src_a.id) in ids
        assert str(src_b.id) in ids
    finally:
        repo.delete_by_canonical_url(canonical)


def test_null_crawl_does_not_overwrite_confirmed_france(db_conn) -> None:
    repo = GiveawayRepository(db_conn)
    url = f"https://lifecycle.test/fr/{uuid4()}"
    canonical = canonicalize_url(url)
    try:
        first = repo.upsert_from_crawl(
            url=url,
            title="FR",
            content_hash="h1",
            eligible_france=True,
            france_eligibility="eligible",
        )
        repo.save_analysis(
            first.giveaway.id,  # type: ignore[arg-type]
            analysis_json={"france_eligibility": "eligible"},
            status=GiveawayStatus.ACTIVE,
            confidence=0.9,
            eligible_france=True,
            france_eligibility="eligible",
            wanted_prize=True,
            entry_acceptable=True,
        )
        second = repo.upsert_from_crawl(
            url=url,
            title="FR weaker",
            content_hash="h2",
            eligible_france=None,
            france_eligibility=None,
        )
        assert second.giveaway.eligible_france is True
        assert second.giveaway.france_eligibility == "eligible"
    finally:
        repo.delete_by_canonical_url(canonical)


def test_terminal_manual_never_sent_to_ai() -> None:
    from app.config import Settings
    from app.models.giveaway import Giveaway

    settings = MagicMock(spec=Settings)
    settings.crawl_candidate_threshold = 0.45
    g = Giveaway(
        id=uuid4(),
        canonical_url="https://x.example/g",
        original_url="https://x.example/g",
        domain="x.example",
        title="Jeu concours — gagnez un cadeau",
        content_hash="abc",
        raw_excerpt=(
            "Participez à notre jeu concours et remportez un cadeau. "
            "Tirage au sort. Date limite. Règlement du jeu. Pour participer."
        ),
        status=GiveawayStatus.CANDIDATE,
        analyzed_at=None,
        manual_status=ManualStatus.ENTERED,
    )
    assert (
        should_skip_analysis(g, settings=settings, reanalyze=False)
        == SkipReason.TERMINAL_MANUAL
    )


def test_analyze_queue_only_never_analyzed(db_conn) -> None:
    repo = GiveawayRepository(db_conn)
    token = uuid4().hex[:8]
    urls = []
    try:
        pending = repo.upsert_from_crawl(
            url=f"https://lifecycle.test/q/{token}/new",
            title="Jeu concours officiel — gagnez",
            raw_excerpt=(
                "Participez à notre jeu concours et remportez un cadeau. "
                "Tirage au sort. Date limite. Règlement du jeu. Pour participer."
            ),
            content_hash=compute_content_hash("a", None, "b"),
        )
        done = repo.upsert_from_crawl(
            url=f"https://lifecycle.test/q/{token}/old",
            title="Jeu concours officiel — gagnez",
            raw_excerpt=(
                "Participez à notre jeu concours et remportez un cadeau. "
                "Tirage au sort. Date limite. Règlement du jeu. Pour participer."
            ),
            content_hash=compute_content_hash("c", None, "d"),
        )
        repo.save_analysis(
            done.giveaway.id,  # type: ignore[arg-type]
            analysis_json={"ok": True},
            status=GiveawayStatus.ACTIVE,
            confidence=0.9,
        )
        urls = [
            canonicalize_url(f"https://lifecycle.test/q/{token}/new"),
            canonicalize_url(f"https://lifecycle.test/q/{token}/old"),
        ]
        queue = repo.list_for_analysis(limit=500, include_analyzed=False)
        ids = {str(g.id) for g in queue}
        assert str(pending.giveaway.id) in ids
        assert str(done.giveaway.id) not in ids
        # include_analyzed / --force path still available
        forced = repo.list_for_analysis(limit=500, include_analyzed=True)
        forced_ids = {str(g.id) for g in forced}
        assert str(done.giveaway.id) in forced_ids
    finally:
        for u in urls:
            repo.delete_by_canonical_url(u)


def test_expired_rows_remain_stored(db_conn) -> None:
    repo = GiveawayRepository(db_conn)
    url = f"https://lifecycle.test/exp/{uuid4()}"
    canonical = canonicalize_url(url)
    try:
        first = repo.upsert_from_crawl(url=url, title="Old", content_hash="h1")
        repo.save_analysis(
            first.giveaway.id,  # type: ignore[arg-type]
            analysis_json={"expired": True},
            status=GiveawayStatus.EXPIRED,
            confidence=0.9,
            end_at=datetime.now(UTC) - timedelta(days=30),
        )
        again = repo.upsert_from_crawl(url=url, title="Old", content_hash="h1")
        assert again.giveaway.status == GiveawayStatus.EXPIRED
        assert again.giveaway.id == first.giveaway.id
        row = repo.get_by_canonical_url(canonical)
        assert row is not None
    finally:
        repo.delete_by_canonical_url(canonical)
