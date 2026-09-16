"""Purge giveaway discovery data without touching schema/sources/migrations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from psycopg import Connection


@dataclass(slots=True, frozen=True)
class PurgePlan:
    giveaways: int
    crawl_runs: int

    @property
    def total(self) -> int:
        return self.giveaways + self.crawl_runs


def plan_purge_giveaways(conn: Connection[Any]) -> PurgePlan:
    g = conn.execute("SELECT count(*)::int AS n FROM giveaways").fetchone()
    c = conn.execute("SELECT count(*)::int AS n FROM crawl_runs").fetchone()
    return PurgePlan(
        giveaways=int(g["n"]) if g else 0,
        crawl_runs=int(c["n"]) if c else 0,
    )


def purge_giveaways(conn: Connection[Any]) -> PurgePlan:
    """
    DELETE giveaway discovery rows + crawl run history.

    Preserves: sources, schema, migrations, application config.
    Does NOT DROP tables.
    """
    before = plan_purge_giveaways(conn)
    # FK-safe order: crawl_runs first (no FK to giveaways), then giveaways.
    conn.execute("DELETE FROM crawl_runs")
    conn.execute("DELETE FROM giveaways")
    return before


def reset_crawl_schedule(conn: Connection[Any]) -> int:
    """Make all enabled sources due for crawl immediately (preserve source rows)."""
    row = conn.execute(
        """
        UPDATE sources
        SET next_crawl_at = now(),
            consecutive_failures = 0,
            last_error_at = NULL,
            updated_at = now()
        WHERE enabled IS TRUE
        RETURNING id
        """
    ).fetchall()
    return len(row)
