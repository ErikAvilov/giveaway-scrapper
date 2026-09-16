"""End-to-end crawl → analyze pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from psycopg import Connection

from app.config import Settings
from app.gemini.service import AnalyzeBatchResult, analyze_giveaways
from app.scraping.runner import SourceCrawlResult, crawl_all

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PipelineSummary:
    pages_fetched: int
    candidates: int
    previously_known: int
    gemini_analyses: int
    confirmed_giveaways: int
    rejected: int
    uncertain: int
    expired: int
    errors: int
    crawl_results: list[SourceCrawlResult]
    analyze_result: AnalyzeBatchResult

    def format(self) -> str:
        lines = [
            "Crawl completed",
            "",
            f"Pages fetched: {self.pages_fetched}",
            f"Candidates: {self.candidates}",
            f"Previously known: {self.previously_known}",
            f"Gemini analyses: {self.gemini_analyses}",
            f"Confirmed giveaways: {self.confirmed_giveaways}",
            f"Rejected: {self.rejected}",
            f"Uncertain: {self.uncertain}",
            f"Expired: {self.expired}",
            f"Errors: {self.errors}",
        ]
        return "\n".join(lines)


def run_pipeline(
    conn: Connection,
    settings: Settings,
    *,
    source_id: UUID | None = None,
    analyze_limit: int = 100,
    only_due: bool = True,
    dry_run: bool = False,
) -> PipelineSummary:
    crawl_results = crawl_all(
        conn,
        settings,
        source_id=source_id,
        dry_run=dry_run,
        only_due=only_due,
    )
    pages = sum(r.pages_fetched for r in crawl_results)
    candidates = sum(r.candidates_found for r in crawl_results)
    previously_known = sum(r.previously_known for r in crawl_results)
    crawl_errors = sum(r.errors_count for r in crawl_results)

    # Hard cap: never inflate beyond the caller-requested limit (cost control).
    analyze_result = analyze_giveaways(
        conn,
        settings,
        limit=analyze_limit,
        dry_run=dry_run,
    )

    return PipelineSummary(
        pages_fetched=pages,
        candidates=candidates,
        previously_known=previously_known,
        gemini_analyses=analyze_result.analyzed,
        confirmed_giveaways=analyze_result.confirmed,
        rejected=analyze_result.rejected,
        uncertain=analyze_result.uncertain,
        expired=analyze_result.expired,
        errors=crawl_errors + analyze_result.errors,
        crawl_results=crawl_results,
        analyze_result=analyze_result,
    )
