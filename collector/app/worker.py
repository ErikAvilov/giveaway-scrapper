"""Long-running scheduler for Raspberry Pi deployments."""

from __future__ import annotations

import gc
import logging
import signal
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from psycopg import OperationalError
from psycopg.errors import Error as PsycopgError

from app.config import Settings, get_settings
from app.db.connection import connect
from app.db.migrate import apply_migrations
from app.db.repository import SourceRepository
from app.gemini.service import analyze_giveaways
from app.scraping.runner import crawl_all

logger = logging.getLogger(__name__)

# Arbitrary stable key for pg_advisory_lock (single-worker crawl batch).
_CRAWL_BATCH_LOCK_KEY = 0x67_17_EA_01  # "giveaway" flavored constant


@dataclass(slots=True)
class WorkerState:
    stop: bool = False
    consecutive_errors: int = 0
    last_tick_at: datetime | None = None
    last_work_at: datetime | None = None
    ticks: int = 0


def _utcnow() -> datetime:
    return datetime.now(UTC)


def write_heartbeat(path: Path, *, status: str, detail: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = f"ts={_utcnow().isoformat()} status={status}"
    if detail:
        payload += f" {detail}"
    path.write_text(payload + "\n", encoding="utf-8")


def _try_lock(conn: Any) -> bool:
    row = conn.execute("SELECT pg_try_advisory_lock(%s) AS ok", (_CRAWL_BATCH_LOCK_KEY,)).fetchone()
    return bool(row and row["ok"])


def _unlock(conn: Any) -> None:
    conn.execute("SELECT pg_advisory_unlock(%s)", (_CRAWL_BATCH_LOCK_KEY,))


def _pending_analysis_count(conn: Any) -> int:
    row = conn.execute(
        """
        SELECT count(*)::int AS n FROM giveaways
        WHERE analyzed_at IS NULL AND status = 'candidate'
        """
    ).fetchone()
    assert row is not None
    return int(row["n"])


def run_worker_tick(settings: Settings, state: WorkerState) -> bool:
    """
    One scheduler iteration.

    Returns True if crawl and/or analyze did meaningful work.
    Ensures only one crawl batch runs at a time via Postgres advisory lock.
    """
    did_work = False
    conn = connect(settings)
    try:
        apply_migrations(conn)
        conn.commit()

        sources = SourceRepository(conn)
        due = sources.list_due_for_crawl()
        pending = _pending_analysis_count(conn)
        logger.info(
            "worker health status=tick due_sources=%s pending_analysis=%s consecutive_errors=%s",
            len(due),
            pending,
            state.consecutive_errors,
        )

        if not due and pending == 0:
            return False

        if due:
            if not _try_lock(conn):
                logger.warning(
                    "worker health status=busy reason=another_crawl_batch_holds_lock"
                )
                return False
            try:
                write_heartbeat(
                    Path(settings.worker_heartbeat_path),
                    status="crawl_running",
                    detail=f"sources={len(due)}",
                )
                logger.info(
                    "worker health status=crawl_start sources=%s",
                    ",".join(s.name for s in due),
                )
                # Sequential per-source processing lives inside crawl_all.
                results = crawl_all(conn, settings, only_due=True, dry_run=False)
                pages = sum(r.pages_fetched for r in results)
                candidates = sum(r.candidates_found for r in results)
                errors = sum(r.errors_count for r in results)
                logger.info(
                    "worker health status=crawl_done pages=%s candidates=%s errors=%s",
                    pages,
                    candidates,
                    errors,
                )
                did_work = True
                # Drop large candidate payloads from memory ASAP.
                for r in results:
                    r.candidates.clear()
                del results
            finally:
                _unlock(conn)
                conn.commit()

        pending = _pending_analysis_count(conn)
        if pending > 0:
            write_heartbeat(
                Path(settings.worker_heartbeat_path),
                status="analyze_running",
                detail=f"pending={pending}",
            )
            logger.info(
                "worker health status=analyze_start pending=%s limit=%s",
                pending,
                settings.worker_analyze_limit,
            )
            batch = analyze_giveaways(
                conn,
                settings,
                limit=settings.worker_analyze_limit,
                dry_run=False,
            )
            logger.info(
                "worker health status=analyze_done analyzed=%s confirmed=%s "
                "rejected=%s uncertain=%s errors=%s",
                batch.analyzed,
                batch.confirmed,
                batch.rejected,
                batch.uncertain,
                batch.errors,
            )
            did_work = did_work or batch.analyzed > 0 or batch.skipped > 0
            del batch

        return did_work
    finally:
        conn.close()
        # Encourage return of large crawl/parse buffers on a 2 GB Pi.
        gc.collect()


def run_worker(settings: Settings | None = None) -> None:
    """Block forever: poll Neon, crawl due sources, analyze, sleep when idle."""
    settings = settings or get_settings()
    state = WorkerState()
    heartbeat = Path(settings.worker_heartbeat_path)

    def _request_stop(signum: int, _frame: Any) -> None:
        logger.info("worker received signal=%s shutting_down=1", signum)
        state.stop = True

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    logger.info(
        "worker started idle_sleep=%ss error_sleep=%ss analyze_limit=%s heartbeat=%s",
        settings.worker_idle_sleep_seconds,
        settings.worker_error_sleep_seconds,
        settings.worker_analyze_limit,
        heartbeat,
    )
    write_heartbeat(heartbeat, status="started")

    while not state.stop:
        state.ticks += 1
        state.last_tick_at = _utcnow()
        try:
            did_work = run_worker_tick(settings, state)
            state.consecutive_errors = 0
            if did_work:
                state.last_work_at = _utcnow()
                write_heartbeat(heartbeat, status="worked", detail=f"ticks={state.ticks}")
                # Brief pause between productive ticks to avoid tight loops.
                _interruptible_sleep(state, min(5.0, settings.worker_idle_sleep_seconds))
            else:
                write_heartbeat(heartbeat, status="idle", detail=f"ticks={state.ticks}")
                logger.info(
                    "worker health status=idle sleep=%ss",
                    settings.worker_idle_sleep_seconds,
                )
                _interruptible_sleep(state, settings.worker_idle_sleep_seconds)
        except (OperationalError, PsycopgError, ConnectionError, TimeoutError, OSError) as exc:
            state.consecutive_errors += 1
            # Exponential backoff capped — never busy-loop on network blips.
            sleep_for = min(
                settings.worker_error_sleep_seconds * (2 ** min(state.consecutive_errors - 1, 4)),
                300.0,
            )
            logger.warning(
                "worker health status=error consecutive=%s sleep=%.0fs error=%s",
                state.consecutive_errors,
                sleep_for,
                exc,
            )
            write_heartbeat(
                heartbeat,
                status="error",
                detail=f"consecutive={state.consecutive_errors} err={type(exc).__name__}",
            )
            _interruptible_sleep(state, sleep_for)
        except Exception:
            state.consecutive_errors += 1
            logger.exception(
                "worker health status=unexpected_error consecutive=%s",
                state.consecutive_errors,
            )
            write_heartbeat(heartbeat, status="unexpected_error")
            _interruptible_sleep(state, settings.worker_error_sleep_seconds)

    write_heartbeat(heartbeat, status="stopped")
    logger.info("worker stopped cleanly ticks=%s", state.ticks)


def _interruptible_sleep(state: WorkerState, seconds: float) -> None:
    """Sleep in short slices so SIGTERM/SIGINT are handled promptly."""
    deadline = time.monotonic() + max(0.0, seconds)
    while not state.stop and time.monotonic() < deadline:
        time.sleep(min(1.0, deadline - time.monotonic()))
