"""Data access for sources, giveaways, and crawl runs (psycopg 3)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.content import compute_content_hash
from app.models.crawl_run import CrawlRun, CrawlRunStatus
from app.models.giveaway import Giveaway, GiveawayStatus, ManualStatus
from app.models.source import Source, SourceType
from app.urls import canonicalize_url, domain_from_url

logger = logging.getLogger(__name__)


def _is_strong_entry_identity(entry_url: str) -> bool:
    """Only treat known platform entry hosts as strong cross-source identity."""
    try:
        host = domain_from_url(canonicalize_url(entry_url)).lower()
    except ValueError:
        return False
    return host in {"gleam.io", "sweepwidget.com"} or host.endswith(
        (".gleam.io", ".sweepwidget.com")
    )


def _utcnow() -> datetime:

    return datetime.now(UTC)


def _row_to_source(row: dict[str, Any]) -> Source:
    crawl_config = row.get("crawl_config") or {}
    if isinstance(crawl_config, str):
        crawl_config = json.loads(crawl_config)
    return Source(
        id=row["id"],
        name=row["name"],
        base_url=row["base_url"],
        source_type=SourceType(row["source_type"]),
        enabled=row["enabled"],
        crawl_interval_minutes=row["crawl_interval_minutes"],
        last_crawled_at=row["last_crawled_at"],
        next_crawl_at=row["next_crawl_at"],
        crawl_config=dict(crawl_config),
        consecutive_failures=int(row.get("consecutive_failures") or 0),
        last_error_at=row.get("last_error_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_giveaway(row: dict[str, Any]) -> Giveaway:
    analysis = row["analysis_json"]
    if isinstance(analysis, str):
        analysis = json.loads(analysis)
    return Giveaway(
        id=row["id"],
        canonical_url=row["canonical_url"],
        original_url=row["original_url"],
        source_id=row["source_id"],
        domain=row["domain"],
        title=row["title"],
        description=row["description"],
        prize=row["prize"],
        prize_value_eur=row["prize_value_eur"],
        prize_category=row.get("prize_category"),
        wanted_prize=row.get("wanted_prize"),
        prize_priority=row.get("prize_priority"),
        preference_reason=row.get("preference_reason"),
        requires_travel=row.get("requires_travel"),
        requires_additional_spend=row.get("requires_additional_spend"),
        free_entry=row["free_entry"],
        eligible_france=row["eligible_france"],
        france_eligibility=row.get("france_eligibility"),
        eligibility_reason=row.get("eligibility_reason"),
        eligible_countries=_as_str_list(row.get("eligible_countries")),
        excluded_countries=_as_str_list(row.get("excluded_countries")),
        requires_purchase=row["requires_purchase"],
        requires_social=row["requires_social"],
        entry_method=row["entry_method"],
        entry_friction=row.get("entry_friction"),
        geo_restriction=row.get("geo_restriction"),
        platform=row.get("platform"),
        platform_campaign_id=row.get("platform_campaign_id"),
        start_at=row["start_at"],
        end_at=row["end_at"],
        terms_url=row["terms_url"],
        entry_url=row["entry_url"],
        entry_http_status=row.get("entry_http_status"),
        entry_checked_at=row.get("entry_checked_at"),
        entry_url_status=row.get("entry_url_status"),
        entry_fail_count=int(row.get("entry_fail_count") or 0),
        status=GiveawayStatus(row["status"]),
        confidence=row["confidence"],
        content_hash=row["content_hash"],
        discovered_at=row["discovered_at"],
        last_seen_at=row["last_seen_at"],
        analyzed_at=row["analyzed_at"],
        raw_excerpt=row["raw_excerpt"],
        link_hints=_as_str_list(row.get("link_hints")),
        analysis_json=analysis,
        manual_status=ManualStatus(row["manual_status"]),
        manual_status_updated_at=row.get("manual_status_updated_at"),
        remind_at=row.get("remind_at"),
        reminder_hours=row.get("reminder_hours"),
        requires_public_social_action=row.get("requires_public_social_action"),
        entry_acceptable=row.get("entry_acceptable"),
        entry_rejection_reason=row.get("entry_rejection_reason"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parsed = json.loads(value)
        return [str(x) for x in parsed] if isinstance(parsed, list) else []
    if isinstance(value, list):
        return [str(x) for x in value]
    return []


def _row_to_crawl_run(row: dict[str, Any]) -> CrawlRun:
    return CrawlRun(
        id=row["id"],
        source_id=row["source_id"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        status=CrawlRunStatus(row["status"]),
        pages_fetched=row["pages_fetched"],
        candidates_found=row["candidates_found"],
        giveaways_created=row["giveaways_created"],
        giveaways_updated=row["giveaways_updated"],
        errors_count=row["errors_count"],
        error_summary=row["error_summary"],
        created_at=row["created_at"],
    )


@dataclass(frozen=True, slots=True)
class GiveawayUpsertResult:
    """Outcome of an idempotent giveaway upsert."""

    giveaway: Giveaway
    created: bool
    content_hash_changed: bool


class SourceRepository:
    """CRUD and crawl-scheduling helpers for sources."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def count(self) -> int:
        row = self._conn.execute("SELECT count(*) AS n FROM sources").fetchone()
        assert row is not None
        return int(row["n"])

    def get_by_id(self, source_id: UUID) -> Source | None:
        row = self._conn.execute(
            "SELECT * FROM sources WHERE id = %s",
            (source_id,),
        ).fetchone()
        return _row_to_source(row) if row else None

    def list_enabled(self) -> list[Source]:
        rows = self._conn.execute(
            """
            SELECT * FROM sources
            WHERE enabled = TRUE
            ORDER BY name
            """
        ).fetchall()
        return [_row_to_source(r) for r in rows]

    def list_due_for_crawl(self, *, now: datetime | None = None) -> list[Source]:
        """Enabled sources whose next_crawl_at is due (or never scheduled)."""
        at = now or _utcnow()
        rows = self._conn.execute(
            """
            SELECT * FROM sources
            WHERE enabled = TRUE
              AND (next_crawl_at IS NULL OR next_crawl_at <= %s)
            ORDER BY next_crawl_at NULLS FIRST, name
            """,
            (at,),
        ).fetchall()
        return [_row_to_source(r) for r in rows]

    def get_by_base_url(self, base_url: str) -> Source | None:
        row = self._conn.execute(
            "SELECT * FROM sources WHERE base_url = %s LIMIT 1",
            (str(base_url),),
        ).fetchone()
        return _row_to_source(row) if row else None

    def create(
        self,
        *,
        name: str,
        base_url: str,
        source_type: SourceType | str,
        enabled: bool = True,
        crawl_interval_minutes: int = 60,
        next_crawl_at: datetime | None = None,
        crawl_config: dict[str, Any] | None = None,
    ) -> Source:
        row = self._conn.execute(
            """
            INSERT INTO sources (
                name, base_url, source_type, enabled,
                crawl_interval_minutes, next_crawl_at, crawl_config
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                name,
                str(base_url),
                str(source_type),
                enabled,
                crawl_interval_minutes,
                next_crawl_at if next_crawl_at is not None else _utcnow(),
                Jsonb(crawl_config or {}),
            ),
        ).fetchone()
        assert row is not None
        return _row_to_source(row)

    def upsert_by_base_url(
        self,
        *,
        name: str,
        base_url: str,
        source_type: SourceType | str,
        enabled: bool = True,
        crawl_interval_minutes: int = 60,
        crawl_config: dict[str, Any] | None = None,
    ) -> Source:
        """Insert a source or refresh metadata when base_url already exists."""
        existing = self.get_by_base_url(str(base_url))
        if existing is None:
            return self.create(
                name=name,
                base_url=base_url,
                source_type=source_type,
                enabled=enabled,
                crawl_interval_minutes=crawl_interval_minutes,
                crawl_config=crawl_config,
            )
        row = self._conn.execute(
            """
            UPDATE sources
            SET name = %s,
                source_type = %s,
                enabled = %s,
                crawl_interval_minutes = %s,
                crawl_config = %s,
                updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (
                name,
                str(source_type),
                enabled,
                crawl_interval_minutes,
                Jsonb(crawl_config or {}),
                existing.id,
            ),
        ).fetchone()
        assert row is not None
        return _row_to_source(row)

    def mark_crawled(
        self,
        source_id: UUID,
        *,
        crawled_at: datetime | None = None,
        interval_minutes: int | None = None,
    ) -> Source:
        """Set last_crawled_at, reset failure backoff, schedule next crawl."""
        at = crawled_at or _utcnow()
        source = self.get_by_id(source_id)
        if source is None:
            raise LookupError(f"source not found: {source_id}")
        minutes = interval_minutes if interval_minutes is not None else source.crawl_interval_minutes
        next_at = at + timedelta(minutes=minutes)
        row = self._conn.execute(
            """
            UPDATE sources
            SET last_crawled_at = %s,
                next_crawl_at = %s,
                consecutive_failures = 0,
                last_error_at = NULL,
                updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (at, next_at, source_id),
        ).fetchone()
        assert row is not None
        return _row_to_source(row)

    def mark_crawl_failed(
        self,
        source_id: UUID,
        *,
        failed_at: datetime | None = None,
        error_summary: str | None = None,
    ) -> Source:
        """
        Record a crawl failure and delay the next attempt (exponential backoff).

        Prevents a broken source from staying immediately due and being hammered.
        """
        from app.scraping.backoff import failure_backoff_minutes

        at = failed_at or _utcnow()
        source = self.get_by_id(source_id)
        if source is None:
            raise LookupError(f"source not found: {source_id}")
        failures = source.consecutive_failures + 1
        delay = failure_backoff_minutes(failures)
        next_at = at + timedelta(minutes=delay)
        row = self._conn.execute(
            """
            UPDATE sources
            SET consecutive_failures = %s,
                last_error_at = %s,
                next_crawl_at = %s,
                updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (failures, at, next_at, source_id),
        ).fetchone()
        assert row is not None
        logger.warning(
            "source crawl failure id=%s name=%s consecutive_failures=%s next_crawl_in_min=%s",
            source_id,
            source.name,
            failures,
            delay,
        )
        # error_summary is stored on crawl_runs, not logged as free-form secrets
        _ = error_summary
        return _row_to_source(row)


class GiveawayRepository:
    """Giveaway persistence with canonical_url upsert semantics."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def count(self) -> int:
        row = self._conn.execute("SELECT count(*) AS n FROM giveaways").fetchone()
        assert row is not None
        return int(row["n"])

    def get_by_id(self, giveaway_id: UUID) -> Giveaway | None:
        row = self._conn.execute(
            "SELECT * FROM giveaways WHERE id = %s",
            (giveaway_id,),
        ).fetchone()
        return _row_to_giveaway(row) if row else None

    def get_by_canonical_url(self, canonical_url: str) -> Giveaway | None:
        row = self._conn.execute(
            "SELECT * FROM giveaways WHERE canonical_url = %s",
            (canonical_url,),
        ).fetchone()
        return _row_to_giveaway(row) if row else None

    def get_by_platform_campaign(
        self,
        platform: str,
        platform_campaign_id: str,
    ) -> Giveaway | None:
        """Cross-aggregator identity lookup (Gleam / SweepWidget keys)."""
        row = self._conn.execute(
            """
            SELECT * FROM giveaways
            WHERE platform = %s AND platform_campaign_id = %s
            ORDER BY last_seen_at DESC NULLS LAST
            LIMIT 1
            """,
            (platform, platform_campaign_id),
        ).fetchone()
        return _row_to_giveaway(row) if row else None

    def get_by_entry_url(self, entry_url: str) -> Giveaway | None:
        """Lookup by normalized entry URL (strong identity hosts only at call site)."""
        try:
            normalized = canonicalize_url(entry_url)
        except ValueError:
            normalized = entry_url.strip()
        row = self._conn.execute(
            """
            SELECT * FROM giveaways
            WHERE entry_url = %s OR entry_url = %s
            ORDER BY analyzed_at DESC NULLS LAST, last_seen_at DESC NULLS LAST
            LIMIT 1
            """,
            (entry_url.strip(), normalized),
        ).fetchone()
        return _row_to_giveaway(row) if row else None

    def record_giveaway_source(
        self,
        giveaway_id: UUID,
        source_id: UUID,
        *,
        source_url: str | None = None,
        seen_at: datetime | None = None,
    ) -> None:
        """Attach or refresh multi-source provenance (additive)."""
        at = seen_at or _utcnow()
        self._conn.execute(
            """
            INSERT INTO giveaway_sources (
                giveaway_id, source_id, source_url, first_seen_at, last_seen_at
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (giveaway_id, source_id) DO UPDATE SET
                last_seen_at = EXCLUDED.last_seen_at,
                source_url = COALESCE(EXCLUDED.source_url, giveaway_sources.source_url)
            """,
            (giveaway_id, source_id, source_url, at, at),
        )

    def list_giveaway_sources(self, giveaway_id: UUID) -> list[dict[str, object]]:
        rows = self._conn.execute(
            """
            SELECT gs.*, s.name AS source_name
            FROM giveaway_sources gs
            LEFT JOIN sources s ON s.id = gs.source_id
            WHERE gs.giveaway_id = %s
            ORDER BY gs.first_seen_at ASC
            """,
            (giveaway_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_needing_analysis(self, *, limit: int = 100) -> list[Giveaway]:
        """Giveaways that have never been analyzed or whose content changed."""
        return self.list_for_analysis(limit=limit, include_analyzed=False)

    def count_pending_analysis(
        self,
        *,
        include_analyzed: bool = False,
        exclude_ids: list[UUID] | None = None,
        only_ids: list[UUID] | None = None,
    ) -> int:
        """Count rows still in the Gemini pending queue (optionally excluding IDs)."""
        excluded = list(exclude_ids or [])
        only = list(only_ids or [])
        clauses: list[str] = []
        params: list[object] = []
        if not include_analyzed:
            clauses.append("analyzed_at IS NULL")
            clauses.append("status = 'candidate'")
            clauses.append(
                "manual_status NOT IN ('entered', 'ignored', 'won', 'lost')"
            )
        if excluded:
            clauses.append("id <> ALL(%s::uuid[])")
            params.append(excluded)
        if only:
            clauses.append("id = ANY(%s::uuid[])")
            params.append(only)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        row = self._conn.execute(
            f"SELECT count(*)::int AS n FROM giveaways {where}",
            params,
        ).fetchone()
        return int(row["n"]) if row else 0

    def list_for_analysis(
        self,
        *,
        limit: int = 100,
        include_analyzed: bool = False,
        exclude_ids: list[UUID] | None = None,
        only_ids: list[UUID] | None = None,
    ) -> list[Giveaway]:
        """
        Queue for Gemini.

        Default: only rows never successfully Gemini-analyzed (`analyzed_at IS NULL`)
        that are still `candidate` (local skips may change status without analyzed_at).
        Fetches at most `limit` rows (one chunk) — never the full table.
        """
        excluded = list(exclude_ids or [])
        only = list(only_ids or [])
        clauses: list[str] = []
        params: list[object] = []
        if not include_analyzed:
            clauses.append("analyzed_at IS NULL")
            clauses.append("status = 'candidate'")
            clauses.append(
                "manual_status NOT IN ('entered', 'ignored', 'won', 'lost')"
            )
        if excluded:
            clauses.append("id <> ALL(%s::uuid[])")
            params.append(excluded)
        if only:
            clauses.append("id = ANY(%s::uuid[])")
            params.append(only)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        # Prefer likely wanted / high-priority prizes, then unknown, then unwanted.
        rows = self._conn.execute(
            f"""
            SELECT * FROM giveaways
            {where}
            ORDER BY
                CASE
                    WHEN wanted_prize IS TRUE THEN 0
                    WHEN wanted_prize IS NULL THEN 1
                    ELSE 2
                END,
                COALESCE(prize_priority, 40) DESC,
                discovered_at ASC
            LIMIT %s
            """,
            params,
        ).fetchall()
        return [_row_to_giveaway(r) for r in rows]

    def upsert_from_crawl(
        self,
        *,
        url: str,
        content_hash: str | None = None,
        source_id: UUID | None = None,
        title: str | None = None,
        description: str | None = None,
        raw_excerpt: str | None = None,
        link_hints: list[str] | None = None,
        prize: str | None = None,
        prize_value_eur: Decimal | None = None,
        prize_category: str | None = None,
        wanted_prize: bool | None = None,
        prize_priority: int | None = None,
        preference_reason: str | None = None,
        requires_travel: bool | None = None,
        requires_additional_spend: bool | None = None,
        free_entry: bool | None = None,
        eligible_france: bool | None = None,
        france_eligibility: str | None = None,
        eligibility_reason: str | None = None,
        requires_purchase: bool | None = None,
        requires_social: bool | None = None,
        entry_method: str | None = None,
        entry_friction: str | None = None,
        geo_restriction: str | None = None,
        platform: str | None = None,
        platform_campaign_id: str | None = None,
        requires_public_social_action: bool | None = None,
        entry_acceptable: bool | None = None,
        entry_rejection_reason: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        terms_url: str | None = None,
        entry_url: str | None = None,
        status: GiveawayStatus | str = GiveawayStatus.CANDIDATE,
        seen_at: datetime | None = None,
    ) -> GiveawayUpsertResult:
        """
        Insert or update a giveaway keyed by canonical_url (long-term memory).

        - Always refreshes last_seen_at.
        - Soft-dedups via platform_campaign_id then strong entry_url.
        - Never clears analyzed_at / analysis_json on content_hash change.
        - Never overwrites manual_status.
        - Never overwrites confirmed analysis fields with NULL / weaker crawl data
          once analyzed_at is set.
        - Records multi-source provenance in giveaway_sources when source_id set.
        """
        canonical = canonicalize_url(url)
        domain = domain_from_url(canonical)
        hash_value = content_hash or compute_content_hash(title, description, raw_excerpt)
        at = seen_at or _utcnow()
        existing = self.get_by_canonical_url(canonical)
        # Soft cross-aggregator dedup: reuse row when platform campaign already known.
        if existing is None and platform and platform_campaign_id:
            by_platform = self.get_by_platform_campaign(platform, platform_campaign_id)
            if by_platform is not None:
                existing = by_platform
                canonical = str(by_platform.canonical_url)
                domain = domain_from_url(canonical)
        # Strong entry_url identity (platform hosts only — avoid false merges).
        if existing is None and entry_url and _is_strong_entry_identity(entry_url):
            by_entry = self.get_by_entry_url(entry_url)
            if by_entry is not None:
                existing = by_entry
                canonical = str(by_entry.canonical_url)
                domain = domain_from_url(canonical)
        created = existing is None
        hash_changed = created or existing.content_hash != hash_value

        row = self._conn.execute(
            """
            INSERT INTO giveaways (
                canonical_url,
                original_url,
                source_id,
                domain,
                title,
                description,
                prize,
                prize_value_eur,
                prize_category,
                wanted_prize,
                prize_priority,
                preference_reason,
                requires_travel,
                requires_additional_spend,
                free_entry,
                eligible_france,
                france_eligibility,
                eligibility_reason,
                requires_purchase,
                requires_social,
                entry_method,
                entry_friction,
                geo_restriction,
                platform,
                platform_campaign_id,
                requires_public_social_action,
                entry_acceptable,
                entry_rejection_reason,
                start_at,
                end_at,
                terms_url,
                entry_url,
                status,
                content_hash,
                discovered_at,
                last_seen_at,
                raw_excerpt,
                link_hints
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (canonical_url) DO UPDATE SET
                original_url = EXCLUDED.original_url,
                -- Keep earliest primary source; multi-source goes to giveaway_sources.
                source_id = COALESCE(giveaways.source_id, EXCLUDED.source_id),
                last_seen_at = EXCLUDED.last_seen_at,
                updated_at = now(),
                content_hash = EXCLUDED.content_hash,
                -- Refresh crawl text only when content actually changed (or fill NULLs).
                title = CASE
                    WHEN giveaways.title IS NULL THEN EXCLUDED.title
                    WHEN giveaways.content_hash IS DISTINCT FROM EXCLUDED.content_hash
                    THEN COALESCE(EXCLUDED.title, giveaways.title)
                    ELSE giveaways.title
                END,
                description = CASE
                    WHEN giveaways.description IS NULL THEN EXCLUDED.description
                    WHEN giveaways.content_hash IS DISTINCT FROM EXCLUDED.content_hash
                    THEN COALESCE(EXCLUDED.description, giveaways.description)
                    ELSE giveaways.description
                END,
                raw_excerpt = CASE
                    WHEN giveaways.raw_excerpt IS NULL THEN EXCLUDED.raw_excerpt
                    WHEN giveaways.content_hash IS DISTINCT FROM EXCLUDED.content_hash
                    THEN COALESCE(EXCLUDED.raw_excerpt, giveaways.raw_excerpt)
                    ELSE giveaways.raw_excerpt
                END,
                link_hints = CASE
                    WHEN giveaways.content_hash IS DISTINCT FROM EXCLUDED.content_hash
                         AND EXCLUDED.link_hints IS NOT NULL
                         AND jsonb_array_length(EXCLUDED.link_hints) > 0
                    THEN EXCLUDED.link_hints
                    ELSE giveaways.link_hints
                END,
                entry_url = COALESCE(EXCLUDED.entry_url, giveaways.entry_url),
                terms_url = COALESCE(EXCLUDED.terms_url, giveaways.terms_url),
                platform = COALESCE(giveaways.platform, EXCLUDED.platform),
                platform_campaign_id = COALESCE(
                    giveaways.platform_campaign_id, EXCLUDED.platform_campaign_id
                ),
                -- Once Gemini-analyzed: preserve analysis-derived fields.
                -- Otherwise: never overwrite confirmed values with NULL.
                prize = CASE
                    WHEN giveaways.analyzed_at IS NOT NULL
                    THEN COALESCE(giveaways.prize, EXCLUDED.prize)
                    ELSE COALESCE(EXCLUDED.prize, giveaways.prize)
                END,
                prize_value_eur = CASE
                    WHEN giveaways.analyzed_at IS NOT NULL
                    THEN COALESCE(giveaways.prize_value_eur, EXCLUDED.prize_value_eur)
                    ELSE COALESCE(EXCLUDED.prize_value_eur, giveaways.prize_value_eur)
                END,
                prize_category = CASE
                    WHEN giveaways.analyzed_at IS NOT NULL
                    THEN COALESCE(giveaways.prize_category, EXCLUDED.prize_category)
                    ELSE COALESCE(EXCLUDED.prize_category, giveaways.prize_category)
                END,
                wanted_prize = CASE
                    WHEN giveaways.analyzed_at IS NOT NULL
                    THEN giveaways.wanted_prize
                    ELSE COALESCE(EXCLUDED.wanted_prize, giveaways.wanted_prize)
                END,
                prize_priority = CASE
                    WHEN giveaways.analyzed_at IS NOT NULL
                    THEN COALESCE(giveaways.prize_priority, EXCLUDED.prize_priority)
                    ELSE COALESCE(EXCLUDED.prize_priority, giveaways.prize_priority)
                END,
                preference_reason = CASE
                    WHEN giveaways.analyzed_at IS NOT NULL
                    THEN COALESCE(giveaways.preference_reason, EXCLUDED.preference_reason)
                    ELSE COALESCE(EXCLUDED.preference_reason, giveaways.preference_reason)
                END,
                requires_travel = CASE
                    WHEN giveaways.analyzed_at IS NOT NULL
                    THEN COALESCE(giveaways.requires_travel, EXCLUDED.requires_travel)
                    ELSE COALESCE(EXCLUDED.requires_travel, giveaways.requires_travel)
                END,
                requires_additional_spend = CASE
                    WHEN giveaways.analyzed_at IS NOT NULL
                    THEN COALESCE(
                        giveaways.requires_additional_spend,
                        EXCLUDED.requires_additional_spend
                    )
                    ELSE COALESCE(
                        EXCLUDED.requires_additional_spend,
                        giveaways.requires_additional_spend
                    )
                END,
                free_entry = CASE
                    WHEN giveaways.analyzed_at IS NOT NULL
                    THEN COALESCE(giveaways.free_entry, EXCLUDED.free_entry)
                    ELSE COALESCE(EXCLUDED.free_entry, giveaways.free_entry)
                END,
                eligible_france = CASE
                    WHEN giveaways.analyzed_at IS NOT NULL
                    THEN giveaways.eligible_france
                    ELSE COALESCE(EXCLUDED.eligible_france, giveaways.eligible_france)
                END,
                france_eligibility = CASE
                    WHEN giveaways.analyzed_at IS NOT NULL
                    THEN giveaways.france_eligibility
                    ELSE COALESCE(EXCLUDED.france_eligibility, giveaways.france_eligibility)
                END,
                eligibility_reason = CASE
                    WHEN giveaways.analyzed_at IS NOT NULL
                    THEN COALESCE(giveaways.eligibility_reason, EXCLUDED.eligibility_reason)
                    ELSE COALESCE(EXCLUDED.eligibility_reason, giveaways.eligibility_reason)
                END,
                requires_purchase = CASE
                    WHEN giveaways.analyzed_at IS NOT NULL
                    THEN COALESCE(giveaways.requires_purchase, EXCLUDED.requires_purchase)
                    ELSE COALESCE(EXCLUDED.requires_purchase, giveaways.requires_purchase)
                END,
                requires_social = CASE
                    WHEN giveaways.analyzed_at IS NOT NULL
                    THEN COALESCE(giveaways.requires_social, EXCLUDED.requires_social)
                    ELSE COALESCE(EXCLUDED.requires_social, giveaways.requires_social)
                END,
                entry_method = CASE
                    WHEN giveaways.analyzed_at IS NOT NULL
                    THEN COALESCE(giveaways.entry_method, EXCLUDED.entry_method)
                    ELSE COALESCE(EXCLUDED.entry_method, giveaways.entry_method)
                END,
                entry_friction = CASE
                    WHEN giveaways.analyzed_at IS NOT NULL
                    THEN COALESCE(giveaways.entry_friction, EXCLUDED.entry_friction)
                    ELSE COALESCE(EXCLUDED.entry_friction, giveaways.entry_friction)
                END,
                geo_restriction = CASE
                    WHEN giveaways.analyzed_at IS NOT NULL
                    THEN COALESCE(giveaways.geo_restriction, EXCLUDED.geo_restriction)
                    ELSE COALESCE(EXCLUDED.geo_restriction, giveaways.geo_restriction)
                END,
                requires_public_social_action = CASE
                    WHEN giveaways.analyzed_at IS NOT NULL
                    THEN giveaways.requires_public_social_action
                    ELSE COALESCE(
                        EXCLUDED.requires_public_social_action,
                        giveaways.requires_public_social_action
                    )
                END,
                entry_acceptable = CASE
                    WHEN giveaways.analyzed_at IS NOT NULL
                    THEN giveaways.entry_acceptable
                    ELSE COALESCE(EXCLUDED.entry_acceptable, giveaways.entry_acceptable)
                END,
                entry_rejection_reason = CASE
                    WHEN giveaways.analyzed_at IS NOT NULL
                    THEN giveaways.entry_rejection_reason
                    ELSE COALESCE(
                        EXCLUDED.entry_rejection_reason,
                        giveaways.entry_rejection_reason
                    )
                END,
                start_at = COALESCE(EXCLUDED.start_at, giveaways.start_at),
                end_at = COALESCE(EXCLUDED.end_at, giveaways.end_at),
                -- Preserve status once analyzed; allow local reject/expiry for pending.
                status = CASE
                    WHEN giveaways.analyzed_at IS NOT NULL THEN giveaways.status
                    WHEN EXCLUDED.status IN ('rejected', 'expired') THEN EXCLUDED.status
                    ELSE giveaways.status
                END,
                -- Long-term memory: never auto-clear Gemini results on rediscovery.
                analyzed_at = giveaways.analyzed_at,
                analysis_json = giveaways.analysis_json,
                confidence = giveaways.confidence
            RETURNING *
            """,
            (
                canonical,
                url.strip(),
                source_id,
                domain,
                title,
                description,
                prize,
                prize_value_eur,
                prize_category,
                wanted_prize,
                prize_priority,
                preference_reason,
                requires_travel,
                requires_additional_spend,
                free_entry,
                eligible_france,
                france_eligibility,
                eligibility_reason,
                requires_purchase,
                requires_social,
                entry_method,
                entry_friction,
                geo_restriction,
                platform,
                platform_campaign_id,
                requires_public_social_action,
                entry_acceptable,
                entry_rejection_reason,
                start_at,
                end_at,
                terms_url,
                entry_url,
                str(status),
                hash_value,
                at,
                at,
                raw_excerpt,
                Jsonb(list(link_hints or [])),
            ),
        ).fetchone()
        assert row is not None
        giveaway = _row_to_giveaway(row)
        if source_id is not None and giveaway.id is not None:
            self.record_giveaway_source(
                giveaway.id,
                source_id,
                source_url=url.strip(),
                seen_at=at,
            )
            # Reload so callers see unchanged fields after provenance write.
            refreshed = self.get_by_id(giveaway.id)
            if refreshed is not None:
                giveaway = refreshed
        logger.debug(
            "giveaway upsert canonical_url=%s created=%s content_hash_changed=%s",
            canonical,
            created,
            hash_changed,
        )
        return GiveawayUpsertResult(
            giveaway=giveaway,
            created=created,
            content_hash_changed=hash_changed,
        )

    def save_analysis(
        self,
        giveaway_id: UUID,
        *,
        analysis_json: dict[str, Any],
        status: GiveawayStatus | str | None = None,
        confidence: float | None = None,
        title: str | None = None,
        description: str | None = None,
        prize: str | None = None,
        prize_value_eur: Decimal | None = None,
        prize_category: str | None = None,
        wanted_prize: bool | None = None,
        prize_priority: int | None = None,
        preference_reason: str | None = None,
        requires_travel: bool | None = None,
        requires_additional_spend: bool | None = None,
        free_entry: bool | None = None,
        eligible_france: bool | None = None,
        france_eligibility: str | None = None,
        eligibility_reason: str | None = None,
        eligible_countries: list[str] | None = None,
        excluded_countries: list[str] | None = None,
        requires_purchase: bool | None = None,
        requires_social: bool | None = None,
        entry_method: str | None = None,
        requires_public_social_action: bool | None = None,
        entry_acceptable: bool | None = None,
        entry_rejection_reason: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        terms_url: str | None = None,
        entry_url: str | None = None,
        analyzed_at: datetime | None = None,
    ) -> Giveaway:
        """
        Persist a successful Gemini structured analysis.

        Sets analyzed_at. Call ONLY after a validated Gemini result — never from
        API failure / retry-exhaustion handlers. Does not modify manual_status.
        """
        at = analyzed_at or _utcnow()
        row = self._conn.execute(
            """
            UPDATE giveaways SET
                analysis_json = %s,
                analyzed_at = %s,
                status = COALESCE(%s, status),
                confidence = COALESCE(%s, confidence),
                title = COALESCE(%s, title),
                description = COALESCE(%s, description),
                prize = COALESCE(%s, prize),
                prize_value_eur = COALESCE(%s, prize_value_eur),
                prize_category = COALESCE(%s, prize_category),
                wanted_prize = COALESCE(%s, wanted_prize),
                prize_priority = COALESCE(%s, prize_priority),
                preference_reason = COALESCE(%s, preference_reason),
                requires_travel = COALESCE(%s, requires_travel),
                requires_additional_spend = COALESCE(%s, requires_additional_spend),
                free_entry = COALESCE(%s, free_entry),
                eligible_france = COALESCE(%s, eligible_france),
                france_eligibility = COALESCE(%s, france_eligibility),
                eligibility_reason = COALESCE(%s, eligibility_reason),
                eligible_countries = COALESCE(%s, eligible_countries),
                excluded_countries = COALESCE(%s, excluded_countries),
                requires_purchase = COALESCE(%s, requires_purchase),
                requires_social = COALESCE(%s, requires_social),
                entry_method = COALESCE(%s, entry_method),
                requires_public_social_action = COALESCE(%s, requires_public_social_action),
                entry_acceptable = COALESCE(%s, entry_acceptable),
                entry_rejection_reason = COALESCE(%s, entry_rejection_reason),
                start_at = COALESCE(%s, start_at),
                end_at = COALESCE(%s, end_at),
                terms_url = COALESCE(%s, terms_url),
                entry_url = COALESCE(%s, entry_url),
                updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (
                Jsonb(analysis_json),
                at,
                str(status) if status is not None else None,
                confidence,
                title,
                description,
                prize,
                prize_value_eur,
                prize_category,
                wanted_prize,
                prize_priority,
                preference_reason,
                requires_travel,
                requires_additional_spend,
                free_entry,
                eligible_france,
                france_eligibility,
                eligibility_reason,
                Jsonb(list(eligible_countries)) if eligible_countries is not None else None,
                Jsonb(list(excluded_countries)) if excluded_countries is not None else None,
                requires_purchase,
                requires_social,
                entry_method,
                requires_public_social_action,
                entry_acceptable,
                entry_rejection_reason,
                start_at,
                end_at,
                terms_url,
                entry_url,
                giveaway_id,
            ),
        ).fetchone()
        if row is None:
            raise LookupError(f"giveaway not found: {giveaway_id}")
        return _row_to_giveaway(row)

    def save_entry_validation(
        self,
        giveaway_id: UUID,
        *,
        entry_url_status: str,
        entry_http_status: int | None,
        entry_fail_count: int,
        entry_checked_at: datetime | None = None,
        status: GiveawayStatus | str | None = None,
    ) -> Giveaway:
        at = entry_checked_at or _utcnow()
        row = self._conn.execute(
            """
            UPDATE giveaways SET
                entry_url_status = %s,
                entry_http_status = %s,
                entry_fail_count = %s,
                entry_checked_at = %s,
                status = COALESCE(%s, status),
                updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (
                entry_url_status,
                entry_http_status,
                entry_fail_count,
                at,
                str(status) if status is not None else None,
                giveaway_id,
            ),
        ).fetchone()
        if row is None:
            raise LookupError(f"giveaway not found: {giveaway_id}")
        return _row_to_giveaway(row)

    def list_for_link_validation(
        self,
        *,
        limit: int = 50,
        exclude_ids: list[UUID] | None = None,
        only_unchecked: bool = False,
    ) -> list[Giveaway]:
        """Bounded queue of giveaways needing entry URL checks."""
        excluded = list(exclude_ids or [])
        clauses = [
            "(entry_url IS NOT NULL OR canonical_url IS NOT NULL)",
            "status IN ('candidate', 'active', 'uncertain')",
            "(entry_url_status IS NULL OR entry_url_status IN ('unknown', 'temporary_error', 'blocked') OR entry_checked_at IS NULL)",
        ]
        params: list[object] = []
        if only_unchecked:
            clauses.append("(entry_checked_at IS NULL OR entry_url_status IS NULL)")
        if excluded:
            clauses.append("id <> ALL(%s::uuid[])")
            params.append(excluded)
        params.append(limit)
        where = " AND ".join(clauses)
        rows = self._conn.execute(
            f"""
            SELECT * FROM giveaways
            WHERE {where}
            ORDER BY entry_checked_at NULLS FIRST, discovered_at ASC
            LIMIT %s
            """,
            params,
        ).fetchall()
        return [_row_to_giveaway(r) for r in rows]

    def apply_local_skip(
        self,
        giveaway_id: UUID,
        *,
        status: GiveawayStatus | str,
        analysis_json: dict[str, Any],
        confidence: float | None = None,
        eligible_france: bool | None = None,
        france_eligibility: str | None = None,
        eligibility_reason: str | None = None,
        requires_public_social_action: bool | None = None,
        entry_acceptable: bool | None = None,
        entry_rejection_reason: str | None = None,
    ) -> Giveaway:
        """
        Record a local pre-Gemini skip (heuristic / clear expiry / FR ineligible).

        Intentionally leaves analyzed_at NULL so the Gemini-success invariant holds.
        Status change removes the row from the default candidate analysis queue.
        Never modifies manual_status.
        """
        row = self._conn.execute(
            """
            UPDATE giveaways SET
                analysis_json = %s,
                status = %s,
                confidence = COALESCE(%s, confidence),
                eligible_france = COALESCE(%s, eligible_france),
                france_eligibility = COALESCE(%s, france_eligibility),
                eligibility_reason = COALESCE(%s, eligibility_reason),
                requires_public_social_action = COALESCE(%s, requires_public_social_action),
                entry_acceptable = COALESCE(%s, entry_acceptable),
                entry_rejection_reason = COALESCE(%s, entry_rejection_reason),
                updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (
                Jsonb(analysis_json),
                str(status),
                confidence,
                eligible_france,
                france_eligibility,
                eligibility_reason,
                requires_public_social_action,
                entry_acceptable,
                entry_rejection_reason,
                giveaway_id,
            ),
        ).fetchone()
        if row is None:
            raise LookupError(f"giveaway not found: {giveaway_id}")
        return _row_to_giveaway(row)

    def save_entry_acceptability(
        self,
        giveaway_id: UUID,
        *,
        requires_public_social_action: bool | None,
        entry_acceptable: bool | None,
        entry_rejection_reason: str | None,
        status: GiveawayStatus | str | None = None,
    ) -> Giveaway:
        """Persist local / backfill entry-acceptability fields (no analyzed_at)."""
        row = self._conn.execute(
            """
            UPDATE giveaways SET
                requires_public_social_action = %s,
                entry_acceptable = %s,
                entry_rejection_reason = %s,
                status = COALESCE(%s, status),
                updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (
                requires_public_social_action,
                entry_acceptable,
                entry_rejection_reason,
                str(status) if status is not None else None,
                giveaway_id,
            ),
        ).fetchone()
        if row is None:
            raise LookupError(f"giveaway not found: {giveaway_id}")
        return _row_to_giveaway(row)

    def list_for_entry_acceptability_backfill(
        self,
        *,
        limit: int = 500,
        force: bool = False,
    ) -> list[Giveaway]:
        """Rows needing (or forced) entry-acceptability re-evaluation from stored text."""
        clause = "TRUE" if force else "entry_acceptable IS NULL"
        rows = self._conn.execute(
            f"""
            SELECT * FROM giveaways
            WHERE {clause}
            ORDER BY discovered_at DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
        return [_row_to_giveaway(r) for r in rows]

    def list_for_entry_rules_reevaluation(self, *, limit: int = 500) -> list[Giveaway]:
        """Rows previously rejected under the public-social entry gate."""
        rows = self._conn.execute(
            """
            SELECT * FROM giveaways
            WHERE entry_acceptable IS FALSE
              AND (
                requires_public_social_action IS TRUE
                OR entry_rejection_reason ILIKE %s
                OR entry_rejection_reason ILIKE %s
              )
            ORDER BY updated_at DESC NULLS LAST, discovered_at DESC
            LIMIT %s
            """,
            ("%public social%", "%social-media%", limit),
        ).fetchall()
        return [_row_to_giveaway(r) for r in rows]

    def list_for_gleam_enter(
        self,
        *,
        limit: int = 20,
        manual_statuses: list[str] | None = None,
        require_france_eligible: bool = False,
        require_entry_acceptable: bool = True,
        only_ids: list[UUID] | None = None,
    ) -> list[Giveaway]:
        """Queue Gleam campaigns for the desktop Selenium enter bot."""
        statuses = manual_statuses or ["interested", "none"]
        clauses = [
            "platform = 'gleam'",
            "manual_status = ANY(%s)",
            "(entry_url IS NOT NULL OR platform_campaign_id IS NOT NULL)",
            "(entry_url_status IS NULL OR entry_url_status <> 'gone')",
            "status NOT IN ('expired', 'rejected')",
        ]
        params: list[Any] = [statuses]
        if require_entry_acceptable:
            clauses.append("(entry_acceptable IS NULL OR entry_acceptable IS TRUE)")
        if require_france_eligible:
            clauses.append(
                "(france_eligibility = 'eligible' OR eligible_france IS TRUE)"
            )
        if only_ids:
            clauses.append("id = ANY(%s)")
            params.append(only_ids)
        params.append(limit)
        rows = self._conn.execute(
            f"""
            SELECT * FROM giveaways
            WHERE {' AND '.join(clauses)}
            ORDER BY
              CASE manual_status WHEN 'interested' THEN 0 ELSE 1 END,
              COALESCE(prize_priority, 0) DESC,
              last_seen_at DESC NULLS LAST,
              discovered_at DESC NULLS LAST
            LIMIT %s
            """,
            params,
        ).fetchall()
        return [_row_to_giveaway(r) for r in rows]

    def update_manual_status(
        self,
        giveaway_id: UUID,
        manual_status: ManualStatus | str,
    ) -> Giveaway:
        """Set manual_status (dashboard parity — used by Gleam enter bot)."""
        status = (
            manual_status
            if isinstance(manual_status, ManualStatus)
            else ManualStatus(str(manual_status))
        )
        row = self._conn.execute(
            """
            UPDATE giveaways SET
                manual_status = %s,
                manual_status_updated_at = now(),
                updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (status.value, giveaway_id),
        ).fetchone()
        if row is None:
            raise ValueError(f"Giveaway not found: {giveaway_id}")
        return _row_to_giveaway(row)

    def delete_by_canonical_url(self, canonical_url: str) -> bool:
        """Delete a giveaway (used by tests / admin cleanup)."""
        row = self._conn.execute(
            "DELETE FROM giveaways WHERE canonical_url = %s RETURNING id",
            (canonical_url,),
        ).fetchone()
        return row is not None


class CrawlRunRepository:
    """Persist crawler run history."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def count(self) -> int:
        row = self._conn.execute("SELECT count(*) AS n FROM crawl_runs").fetchone()
        assert row is not None
        return int(row["n"])

    def get_by_id(self, run_id: UUID) -> CrawlRun | None:
        row = self._conn.execute(
            "SELECT * FROM crawl_runs WHERE id = %s",
            (run_id,),
        ).fetchone()
        return _row_to_crawl_run(row) if row else None

    def start(
        self,
        *,
        source_id: UUID | None = None,
        started_at: datetime | None = None,
    ) -> CrawlRun:
        at = started_at or _utcnow()
        row = self._conn.execute(
            """
            INSERT INTO crawl_runs (source_id, started_at, status)
            VALUES (%s, %s, %s)
            RETURNING *
            """,
            (source_id, at, CrawlRunStatus.RUNNING.value),
        ).fetchone()
        assert row is not None
        return _row_to_crawl_run(row)

    def finish(
        self,
        run_id: UUID,
        *,
        status: CrawlRunStatus | str,
        pages_fetched: int = 0,
        candidates_found: int = 0,
        giveaways_created: int = 0,
        giveaways_updated: int = 0,
        errors_count: int = 0,
        error_summary: str | None = None,
        finished_at: datetime | None = None,
    ) -> CrawlRun:
        at = finished_at or _utcnow()
        row = self._conn.execute(
            """
            UPDATE crawl_runs SET
                finished_at = %s,
                status = %s,
                pages_fetched = %s,
                candidates_found = %s,
                giveaways_created = %s,
                giveaways_updated = %s,
                errors_count = %s,
                error_summary = %s
            WHERE id = %s
            RETURNING *
            """,
            (
                at,
                str(status),
                pages_fetched,
                candidates_found,
                giveaways_created,
                giveaways_updated,
                errors_count,
                error_summary,
                run_id,
            ),
        ).fetchone()
        if row is None:
            raise LookupError(f"crawl_run not found: {run_id}")
        return _row_to_crawl_run(row)
