"""Tests for source crawl failure backoff."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.db.connection import connection
from app.db.repository import SourceRepository
from app.models.source import SourceType
from app.scraping.backoff import failure_backoff_minutes


@pytest.mark.parametrize(
    ("failures", "expected"),
    [
        (1, 15),
        (2, 30),
        (3, 60),
        (4, 120),
        (5, 240),
        (6, 360),
        (7, 360),
        (20, 360),
    ],
)
def test_failure_backoff_schedule(failures: int, expected: int) -> None:
    assert failure_backoff_minutes(failures) == expected


def test_mark_crawl_failed_schedules_backoff_and_resets_on_success(
    settings, migrated_db
) -> None:
    with connection(settings) as conn:
        repo = SourceRepository(conn)
        name = f"backoff-test-{uuid4().hex[:8]}"
        source = repo.create(
            name=name,
            base_url=f"https://backoff-{uuid4().hex[:8]}.example/",
            source_type=SourceType.OTHER,
            crawl_interval_minutes=60,
            next_crawl_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        assert source.id is not None
        try:
            failed_at = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
            after1 = repo.mark_crawl_failed(source.id, failed_at=failed_at)
            assert after1.consecutive_failures == 1
            assert after1.last_error_at == failed_at
            assert after1.next_crawl_at == failed_at + timedelta(minutes=15)

            # Still within backoff → not due.
            due = {str(s.id) for s in repo.list_due_for_crawl(now=failed_at + timedelta(minutes=5))}
            assert str(source.id) not in due

            after2 = repo.mark_crawl_failed(
                source.id, failed_at=failed_at + timedelta(minutes=15)
            )
            assert after2.consecutive_failures == 2
            assert after2.next_crawl_at == failed_at + timedelta(minutes=15 + 30)

            # Success resets failure state and uses normal interval.
            crawled_at = failed_at + timedelta(hours=2)
            ok = repo.mark_crawled(source.id, crawled_at=crawled_at)
            assert ok.consecutive_failures == 0
            assert ok.last_error_at is None
            assert ok.next_crawl_at == crawled_at + timedelta(minutes=60)
        finally:
            conn.execute("DELETE FROM crawl_runs WHERE source_id = %s", (source.id,))
            conn.execute("DELETE FROM sources WHERE id = %s", (source.id,))
            conn.commit()


def test_broken_source_is_not_immediately_due_again(settings, migrated_db) -> None:
    with connection(settings) as conn:
        repo = SourceRepository(conn)
        source = repo.create(
            name=f"hammer-guard-{uuid4().hex[:8]}",
            base_url=f"https://hammer-{uuid4().hex[:8]}.example/",
            source_type=SourceType.OTHER,
            crawl_interval_minutes=5,
            next_crawl_at=datetime.now(UTC) - timedelta(seconds=30),
        )
        assert source.id is not None
        try:
            now = datetime.now(UTC)
            assert any(s.id == source.id for s in repo.list_due_for_crawl(now=now))

            failed = repo.mark_crawl_failed(source.id, failed_at=now)
            assert failed.consecutive_failures == 1
            assert failed.next_crawl_at is not None
            assert failed.next_crawl_at > now + timedelta(minutes=10)

            soon = now + timedelta(seconds=10)
            assert not any(s.id == source.id for s in repo.list_due_for_crawl(now=soon))
        finally:
            conn.execute("DELETE FROM sources WHERE id = %s", (source.id,))
            conn.commit()
