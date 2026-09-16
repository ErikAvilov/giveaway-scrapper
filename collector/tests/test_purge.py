"""Purge giveaways while preserving sources."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.content import compute_content_hash
from app.db.connection import connection
from app.db.purge import plan_purge_giveaways, purge_giveaways, reset_crawl_schedule
from app.db.repository import CrawlRunRepository, GiveawayRepository
from app.models.crawl_run import CrawlRunStatus
from app.scraping.seed import seed_sources

REAL_SOURCES = Path(__file__).resolve().parents[1] / "config" / "sources.real.json"


def test_purge_removes_giveaways_preserves_sources(settings, migrated_db) -> None:
    url = f"https://purge.test/g/{uuid4()}"
    with connection(settings) as conn:
        sources_before = seed_sources(conn, REAL_SOURCES)
        conn.commit()
        source_count = conn.execute("SELECT count(*)::int AS n FROM sources").fetchone()
        assert source_count is not None
        n_sources = int(source_count["n"])
        assert n_sources >= len(sources_before)

        giveaways = GiveawayRepository(conn)
        giveaways.upsert_from_crawl(
            url=url,
            title="Temp",
            raw_excerpt="Jeu concours France",
            content_hash=compute_content_hash("Temp", None, "Jeu concours France"),
        )
        enabled = [s for s in sources_before if s.enabled]
        assert enabled and enabled[0].id is not None
        runs = CrawlRunRepository(conn)
        run = runs.start(source_id=enabled[0].id)
        assert run.id is not None
        runs.finish(
            run.id,
            status=CrawlRunStatus.SUCCESS,
            pages_fetched=1,
            candidates_found=1,
            giveaways_created=1,
            giveaways_updated=0,
            errors_count=0,
        )
        conn.commit()

        plan = plan_purge_giveaways(conn)
        assert plan.giveaways >= 1
        assert plan.crawl_runs >= 1

        deleted = purge_giveaways(conn)
        conn.commit()
        assert deleted.giveaways == plan.giveaways
        assert deleted.crawl_runs == plan.crawl_runs

        after_g = conn.execute("SELECT count(*)::int AS n FROM giveaways").fetchone()
        after_c = conn.execute("SELECT count(*)::int AS n FROM crawl_runs").fetchone()
        after_s = conn.execute("SELECT count(*)::int AS n FROM sources").fetchone()
        assert after_g is not None and int(after_g["n"]) == 0
        assert after_c is not None and int(after_c["n"]) == 0
        assert after_s is not None and int(after_s["n"]) == n_sources

        reset_n = reset_crawl_schedule(conn)
        conn.commit()
        assert reset_n >= 1
