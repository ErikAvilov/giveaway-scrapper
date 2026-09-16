"""Orchestrate per-source crawls and persist candidates."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from psycopg import Connection

from app.config import Settings
from app.content import compute_content_hash
from app.db.repository import CrawlRunRepository, GiveawayRepository, SourceRepository
from app.models.crawl_run import CrawlRunStatus
from app.models.source import Source
from app.scraping.real_test import (
    RealTestOverrides,
    apply_real_test_limits,
    is_real_profile,
)
from app.scraping.spider import SpiderLimits, build_spider, run_spider
from app.urls import domain_from_url

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SourceCrawlResult:
    source_id: UUID
    source_name: str
    pages_fetched: int
    candidates_found: int
    giveaways_created: int
    giveaways_updated: int
    previously_known: int
    needs_analysis: int
    errors_count: int
    status: CrawlRunStatus
    error_summary: str | None
    candidate_threshold: float = 0.45
    # Kept for dry-run / real-test diagnostics; cleared after persistence otherwise.
    candidates: list[dict[str, Any]] = field(default_factory=list)


def _limits_for_source(source: Source, settings: Settings) -> SpiderLimits:
    cfg = source.crawl_config or {}
    return SpiderLimits(
        max_depth=int(cfg.get("max_depth", settings.crawl_max_depth)),
        max_pages=int(cfg.get("max_pages", settings.crawl_max_pages_per_source)),
        candidate_threshold=float(
            cfg.get("candidate_threshold", settings.crawl_candidate_threshold)
        ),
        excerpt_max_chars=int(
            cfg.get("raw_excerpt_max_chars", settings.crawl_raw_excerpt_max_chars)
        ),
        request_timeout=float(cfg.get("request_timeout", settings.crawl_request_timeout)),
        retries=int(cfg.get("retries", settings.crawl_retries)),
    )


def crawl_source(
    conn: Connection,
    settings: Settings,
    source: Source,
    *,
    dry_run: bool = False,
    real_test: bool = False,
    real_test_overrides: RealTestOverrides | None = None,
) -> SourceCrawlResult:
    """Crawl one source. Never raises for site-level failures — returns failed status."""
    assert source.id is not None
    runs = CrawlRunRepository(conn)
    giveaways = GiveawayRepository(conn)
    sources = SourceRepository(conn)

    run = None if dry_run else runs.start(source_id=source.id)
    candidates: list[dict[str, Any]] = []
    created = 0
    updated = 0
    previously_known = 0
    needs_analysis = 0
    candidates_found = 0
    pages = 0
    errors = 0
    error_summary: str | None = None
    status = CrawlRunStatus.SUCCESS
    retain_candidates = dry_run or real_test
    threshold = settings.crawl_candidate_threshold

    try:
        base = str(source.base_url)
        domain = domain_from_url(base)
        limits = _limits_for_source(source, settings)
        concurrent_requests = settings.crawl_concurrent_requests
        concurrent_per_domain = settings.crawl_concurrent_requests_per_domain
        if real_test:
            limits = apply_real_test_limits(limits, settings)
            overrides = real_test_overrides or RealTestOverrides()
            concurrent_requests = overrides.concurrent_requests
            concurrent_per_domain = overrides.concurrent_requests_per_domain

        adapter_key = (source.crawl_config or {}).get("adapter")
        extra_starts = (source.crawl_config or {}).get("extra_start_urls") or []
        if not isinstance(extra_starts, list):
            extra_starts = []
        spider = build_spider(
            source_id=source.id,
            start_url=base,
            allowed_domain=domain,
            concurrent_requests=concurrent_requests,
            concurrent_requests_per_domain=concurrent_per_domain,
            download_delay=settings.crawl_download_delay,
            autothrottle=settings.crawl_autothrottle,
            autothrottle_start_delay=settings.crawl_autothrottle_start_delay,
            autothrottle_max_delay=settings.crawl_autothrottle_max_delay,
            limits=limits,
            adapter_key=str(adapter_key) if adapter_key else None,
            source_name=source.name,
            extra_start_urls=[str(u) for u in extra_starts],
        )
        candidates, stats = run_spider(spider)
        pages = int(stats.get("pages_fetched_local") or stats.get("requests_count") or 0)
        engine_errors = int(stats.get("failed_requests_count") or 0) + int(
            stats.get("blocked_requests_count") or 0
        )
        errors = engine_errors
        # Drop spider graph promptly on a 2 GB Pi.
        del spider
        del stats
        candidates_found = len(candidates)
        threshold = limits.candidate_threshold

        if not dry_run:
            for item in candidates:
                # Prefer stable aggregator detail URL when present (child listings).
                persist_url = str(item.get("url") or item.get("original_url") or "")
                status_raw = item.get("status")
                result = giveaways.upsert_from_crawl(
                    url=persist_url,
                    source_id=source.id,
                    title=item.get("title"),
                    prize=item.get("prize"),
                    raw_excerpt=item.get("raw_excerpt"),
                    link_hints=list(item.get("link_hints") or []),
                    entry_url=item.get("entry_url"),
                    terms_url=item.get("terms_url"),
                    free_entry=item.get("free_entry"),
                    eligible_france=item.get("eligible_france"),
                    france_eligibility=item.get("france_eligibility"),
                    eligibility_reason=item.get("eligibility_reason"),
                    requires_purchase=item.get("requires_purchase"),
                    requires_social=item.get("requires_social"),
                    entry_method=item.get("entry_method"),
                    entry_friction=item.get("entry_friction"),
                    geo_restriction=item.get("geo_restriction"),
                    prize_category=item.get("prize_category"),
                    wanted_prize=item.get("wanted_prize"),
                    prize_priority=item.get("prize_priority"),
                    preference_reason=item.get("preference_reason"),
                    requires_travel=item.get("requires_travel"),
                    requires_additional_spend=item.get("requires_additional_spend"),
                    requires_public_social_action=item.get("requires_public_social_action"),
                    entry_acceptable=item.get("entry_acceptable"),
                    entry_rejection_reason=item.get("entry_rejection_reason"),
                    platform=item.get("platform"),
                    platform_campaign_id=item.get("platform_campaign_id"),
                    status=status_raw or "candidate",
                    content_hash=compute_content_hash(
                        item.get("title"),
                        None,
                        item.get("raw_excerpt"),
                    ),
                )
                if result.created:
                    created += 1
                    needs_analysis += 1
                else:
                    updated += 1
                    if result.content_hash_changed:
                        needs_analysis += 1
                    else:
                        previously_known += 1

            if errors and not candidates and pages == 0:
                status = CrawlRunStatus.FAILED
                error_summary = "Crawl produced no pages (blocked, network, or robots.txt)"
                sources.mark_crawl_failed(source.id, error_summary=error_summary)
            else:
                if errors and candidates:
                    status = CrawlRunStatus.PARTIAL
                sources.mark_crawled(source.id)
            if not retain_candidates:
                candidates.clear()
        else:
            needs_analysis = candidates_found
            if errors and candidates:
                status = CrawlRunStatus.PARTIAL
            elif errors and not candidates and pages == 0:
                status = CrawlRunStatus.FAILED
                error_summary = "Crawl produced no pages (blocked, network, or robots.txt)"
    except Exception as exc:
        logger.exception("crawl failed source_id=%s name=%s", source.id, source.name)
        status = CrawlRunStatus.FAILED
        errors = max(errors, 1)
        error_summary = f"{type(exc).__name__}: {exc}"[:1000]
        candidates_found = len(candidates)
        threshold = _limits_for_source(source, settings).candidate_threshold
        if not dry_run:
            try:
                sources.mark_crawl_failed(source.id, error_summary=error_summary)
            except Exception:
                logger.exception("failed to record crawl backoff source_id=%s", source.id)
            if not retain_candidates:
                candidates.clear()

    if run is not None:
        runs.finish(
            run.id,  # type: ignore[arg-type]
            status=status,
            pages_fetched=pages,
            candidates_found=candidates_found,
            giveaways_created=created,
            giveaways_updated=updated,
            errors_count=errors,
            error_summary=error_summary,
        )
        conn.commit()

    return SourceCrawlResult(
        source_id=source.id,
        source_name=source.name,
        pages_fetched=pages,
        candidates_found=candidates_found,
        giveaways_created=created,
        giveaways_updated=updated,
        previously_known=previously_known,
        needs_analysis=needs_analysis,
        errors_count=errors,
        status=status,
        error_summary=error_summary,
        candidate_threshold=threshold,
        candidates=candidates if retain_candidates else [],
    )


def crawl_all(
    conn: Connection,
    settings: Settings,
    *,
    source_id: UUID | None = None,
    dry_run: bool = False,
    only_due: bool = True,
    real_test: bool = False,
    real_profile_only: bool = False,
) -> list[SourceCrawlResult]:
    """
    Crawl due/enabled sources. A failure on one source does not stop the others.
    """
    repo = SourceRepository(conn)
    if source_id is not None:
        source = repo.get_by_id(source_id)
        if source is None:
            raise LookupError(f"Source not found: {source_id}")
        targets = [source]
    elif only_due:
        targets = repo.list_due_for_crawl()
    else:
        targets = repo.list_enabled()

    if real_profile_only:
        targets = [s for s in targets if is_real_profile(s.crawl_config)]

    results: list[SourceCrawlResult] = []
    for source in targets:
        logger.info(
            "crawl start source=%s url=%s dry_run=%s real_test=%s",
            source.name,
            source.base_url,
            dry_run,
            real_test,
        )
        try:
            results.append(
                crawl_source(
                    conn,
                    settings,
                    source,
                    dry_run=dry_run,
                    real_test=real_test,
                )
            )
        except Exception as exc:
            logger.exception("unexpected crawl orchestration error source=%s", source.name)
            assert source.id is not None
            if not dry_run:
                try:
                    repo.mark_crawl_failed(source.id, error_summary=str(exc)[:1000])
                    conn.commit()
                except Exception:
                    logger.exception("failed to record crawl backoff source_id=%s", source.id)
            results.append(
                SourceCrawlResult(
                    source_id=source.id,
                    source_name=source.name,
                    pages_fetched=0,
                    candidates_found=0,
                    giveaways_created=0,
                    giveaways_updated=0,
                    previously_known=0,
                    needs_analysis=0,
                    errors_count=1,
                    status=CrawlRunStatus.FAILED,
                    error_summary=str(exc)[:1000],
                    candidates=[],
                )
            )
    return results
