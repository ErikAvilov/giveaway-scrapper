"""Collector runtime statistics from Neon."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from psycopg import Connection


@dataclass(slots=True, frozen=True)
class CollectorStats:
    enabled_sources: int
    total_giveaways: int
    active_giveaways: int
    free_giveaways: int
    france_eligible_giveaways: int
    giveaways_discovered_today: int
    pages_crawled_today: int
    gemini_analyses_today: int
    errors_last_24h: int

    def as_lines(self) -> list[str]:
        return [
            f"Enabled sources:              {self.enabled_sources}",
            f"Total giveaways:              {self.total_giveaways}",
            f"Active giveaways:             {self.active_giveaways}",
            f"Free giveaways:               {self.free_giveaways}",
            f"France-eligible giveaways:    {self.france_eligible_giveaways}",
            f"Giveaways discovered today:   {self.giveaways_discovered_today}",
            f"Pages crawled today:          {self.pages_crawled_today}",
            f"Gemini analyses today:        {self.gemini_analyses_today}",
            f"Errors during last 24h:       {self.errors_last_24h}",
        ]


def fetch_collector_stats(conn: Connection) -> CollectorStats:
    row = conn.execute(
        """
        SELECT
            (SELECT count(*)::int FROM sources WHERE enabled = TRUE) AS enabled_sources,
            (SELECT count(*)::int FROM giveaways) AS total_giveaways,
            (SELECT count(*)::int FROM giveaways WHERE status = 'active') AS active_giveaways,
            (SELECT count(*)::int FROM giveaways WHERE free_entry IS TRUE) AS free_giveaways,
            (SELECT count(*)::int FROM giveaways WHERE eligible_france IS TRUE)
                AS france_eligible_giveaways,
            (SELECT count(*)::int FROM giveaways
             WHERE discovered_at >= date_trunc('day', now() AT TIME ZONE 'UTC'))
                AS giveaways_discovered_today,
            (SELECT coalesce(sum(pages_fetched), 0)::int FROM crawl_runs
             WHERE started_at >= date_trunc('day', now() AT TIME ZONE 'UTC'))
                AS pages_crawled_today,
            (SELECT count(*)::int FROM giveaways
             WHERE analyzed_at >= date_trunc('day', now() AT TIME ZONE 'UTC')
               AND coalesce(analysis_json->'_meta'->>'model', '') <> '')
                AS gemini_analyses_today,
            (SELECT coalesce(sum(errors_count), 0)::int FROM crawl_runs
             WHERE started_at >= now() - interval '24 hours') AS errors_last_24h
        """
    ).fetchone()
    assert row is not None
    data: dict[str, Any] = dict(row)
    return CollectorStats(
        enabled_sources=int(data["enabled_sources"]),
        total_giveaways=int(data["total_giveaways"]),
        active_giveaways=int(data["active_giveaways"]),
        free_giveaways=int(data["free_giveaways"]),
        france_eligible_giveaways=int(data["france_eligible_giveaways"]),
        giveaways_discovered_today=int(data["giveaways_discovered_today"]),
        pages_crawled_today=int(data["pages_crawled_today"]),
        gemini_analyses_today=int(data["gemini_analyses_today"]),
        errors_last_24h=int(data["errors_last_24h"]),
    )
