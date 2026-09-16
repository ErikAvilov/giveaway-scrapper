"""Tests for stats queries and worker helpers."""

from __future__ import annotations

from pathlib import Path

from app.db.connection import connection
from app.db.stats import fetch_collector_stats
from app.worker import WorkerState, _interruptible_sleep, write_heartbeat


def test_fetch_collector_stats(settings, migrated_db) -> None:
    with connection(settings) as conn:
        stats = fetch_collector_stats(conn)
    assert stats.enabled_sources >= 0
    assert stats.total_giveaways >= 0
    assert stats.active_giveaways >= 0
    assert stats.errors_last_24h >= 0


def test_heartbeat_write(tmp_path: Path) -> None:
    path = tmp_path / "hb"
    write_heartbeat(path, status="idle", detail="ticks=1")
    text = path.read_text(encoding="utf-8")
    assert "status=idle" in text
    assert "ticks=1" in text


def test_interruptible_sleep_respects_stop() -> None:
    state = WorkerState(stop=True)
    started = __import__("time").monotonic()
    _interruptible_sleep(state, 30.0)
    assert __import__("time").monotonic() - started < 2.0
