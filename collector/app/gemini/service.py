"""Apply Gemini analysis to giveaway candidates (micro-batched)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from psycopg import Connection

from app.config import Settings
from app.db.repository import GiveawayRepository
from app.extraction.entry_acceptability import (
    REJECTION_REASON as ENTRY_SOCIAL_REJECTION,
)
from app.extraction.entry_acceptability import (
    assess_entry_acceptability,
    merge_entry_acceptability,
)
from app.extraction.france_eligibility import (
    FranceEligibility,
    classify_france_eligibility,
    sync_eligible_france_column,
)
from app.gemini.client import GeminiBatchResult, GeminiClient, GiveawayPageInput
from app.gemini.guards import (
    heuristic_below_threshold,
    looks_clearly_expired,
    looks_undesirable_for_gemini,
)
from app.gemini.schema import GiveawayAnalysis, GiveawayBatchItemAnalysis
from app.models.giveaway import Giveaway, GiveawayStatus, ManualStatus

logger = logging.getLogger(__name__)


class SkipReason(StrEnum):
    ALREADY_ANALYZED = "already_analyzed"
    HEURISTIC_REJECTED = "heuristic_rejected"
    CLEARLY_EXPIRED = "clearly_expired"
    UNDESIRABLE = "undesirable"
    FRANCE_INELIGIBLE = "france_ineligible"
    PUBLIC_SOCIAL = "public_social"
    TERMINAL_MANUAL = "terminal_manual"
    MISSING_CONTENT = "missing_content"


@dataclass(slots=True)
class AnalyzeItemResult:
    giveaway_id: UUID
    canonical_url: str
    skipped: bool
    skip_reason: SkipReason | None = None
    status: GiveawayStatus | None = None
    is_giveaway: bool | None = None
    confidence: float | None = None
    error: str | None = None
    analysis: GiveawayAnalysis | None = None
    pending: bool = False


@dataclass(slots=True)
class AnalyzeBatchResult:
    processed: int = 0
    analyzed: int = 0
    skipped: int = 0
    confirmed: int = 0
    rejected: int = 0
    uncertain: int = 0
    expired: int = 0
    errors: int = 0
    api_requests: int = 0
    pending: int = 0
    items: list[AnalyzeItemResult] = field(default_factory=list)


def resolve_france_eligibility(analysis: GiveawayAnalysis) -> FranceEligibility:
    """Prefer france_eligibility; fall back to eligible_france for compat."""
    state = analysis.france_eligibility
    if state is not None and state != FranceEligibility.UNKNOWN:
        return FranceEligibility(state)
    if analysis.eligible_france is True:
        return FranceEligibility.ELIGIBLE
    if analysis.eligible_france is False:
        return FranceEligibility.INELIGIBLE
    if state is not None:
        return FranceEligibility(state)
    return FranceEligibility.UNKNOWN


def decide_status(
    analysis: GiveawayAnalysis,
    *,
    now: datetime | None = None,
    entry_url_status: str | None = None,
) -> GiveawayStatus:
    """Map structured analysis to a DB status (France-first + prize gate)."""
    at = now or datetime.now(UTC)
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)

    if not analysis.is_giveaway:
        return GiveawayStatus.REJECTED

    if entry_url_status == "gone":
        return GiveawayStatus.REJECTED

    france = resolve_france_eligibility(analysis)
    if france == FranceEligibility.INELIGIBLE:
        return GiveawayStatus.REJECTED

    if analysis.wanted_prize is False:
        return GiveawayStatus.REJECTED

    if (
        analysis.entry_acceptable is False
        or analysis.requires_public_social_action is True
    ):
        return GiveawayStatus.REJECTED

    if analysis.end_date is not None:
        end = analysis.end_date
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        if end < at:
            return GiveawayStatus.EXPIRED

    if analysis.confidence < 0.5:
        return GiveawayStatus.UNCERTAIN

    # Never activate without positive France evidence.
    if france != FranceEligibility.ELIGIBLE:
        return GiveawayStatus.UNCERTAIN

    # Unknown entry acceptability stays pending until resolved.
    if analysis.entry_acceptable is None:
        return GiveawayStatus.UNCERTAIN

    return GiveawayStatus.ACTIVE


def should_skip_analysis(
    giveaway: Giveaway,
    *,
    settings: Settings,
    reanalyze: bool,
) -> SkipReason | None:
    if not (giveaway.raw_excerpt or giveaway.title):
        return SkipReason.MISSING_CONTENT
    if giveaway.analyzed_at is not None and not reanalyze:
        return SkipReason.ALREADY_ANALYZED
    # Terminal user decisions are sacred — never auto-send to AI again.
    if giveaway.manual_status in {
        ManualStatus.ENTERED,
        ManualStatus.IGNORED,
        ManualStatus.WON,
        ManualStatus.LOST,
    }:
        return SkipReason.TERMINAL_MANUAL
    if heuristic_below_threshold(giveaway, threshold=settings.crawl_candidate_threshold):
        return SkipReason.HEURISTIC_REJECTED
    if looks_clearly_expired(giveaway):
        return SkipReason.CLEARLY_EXPIRED
    if looks_undesirable_for_gemini(giveaway):
        return SkipReason.UNDESIRABLE

    local_fr = classify_france_eligibility(
        title=giveaway.title,
        prize=giveaway.prize,
        body=giveaway.raw_excerpt,
        restriction=giveaway.geo_restriction,
    )
    if local_fr.france_eligibility == FranceEligibility.INELIGIBLE:
        return SkipReason.FRANCE_INELIGIBLE

    requirements: list[str] = []
    platform_actions: list[dict[str, Any]] = []
    actions_required: int | None = None
    if isinstance(giveaway.analysis_json, dict):
        raw_req = giveaway.analysis_json.get("requirements")
        if isinstance(raw_req, list):
            requirements = [str(r) for r in raw_req if r]
        from app.extraction.entry_acceptability_backfill import (
            _actions_required_from_analysis,
            _platform_actions_from_analysis,
        )

        platform_actions = _platform_actions_from_analysis(giveaway.analysis_json)
        actions_required = _actions_required_from_analysis(giveaway.analysis_json)
    local_entry = assess_entry_acceptability(
        title=giveaway.title,
        prize=giveaway.prize,
        body=giveaway.raw_excerpt,
        entry_method=giveaway.entry_method,
        requirements=requirements,
        platform_actions=platform_actions or None,
        actions_required=actions_required,
    )
    if local_entry.entry_acceptable is False:
        return SkipReason.PUBLIC_SOCIAL
    return None


def analysis_to_json(analysis: GiveawayAnalysis, *, model: str) -> dict[str, Any]:
    payload = analysis.model_dump(mode="json")
    payload["_meta"] = {"model": model}
    return payload


def apply_analysis(
    repo: GiveawayRepository,
    giveaway: Giveaway,
    analysis: GiveawayAnalysis,
    *,
    model: str,
) -> Giveaway:
    assert giveaway.id is not None
    france = resolve_france_eligibility(analysis)
    eligible_france = sync_eligible_france_column(france)

    requirements = list(analysis.requirements or [])
    platform_actions: list[dict[str, Any]] = []
    actions_required: int | None = None
    if isinstance(giveaway.analysis_json, dict):
        from app.extraction.entry_acceptability_backfill import (
            _actions_required_from_analysis,
            _platform_actions_from_analysis,
        )

        platform_actions = _platform_actions_from_analysis(giveaway.analysis_json)
        actions_required = _actions_required_from_analysis(giveaway.analysis_json)
    local_entry = assess_entry_acceptability(
        title=analysis.title or giveaway.title,
        prize=analysis.prize or giveaway.prize,
        body=analysis.summary or giveaway.raw_excerpt,
        entry_method=(
            analysis.entry_method.value
            if analysis.entry_method is not None
            else giveaway.entry_method
        ),
        requirements=requirements,
        platform_actions=platform_actions or None,
        actions_required=actions_required,
    )
    entry = merge_entry_acceptability(
        local_entry,
        gemini_requires_public=analysis.requires_public_social_action,
        gemini_acceptable=analysis.entry_acceptable,
        gemini_reason=analysis.entry_rejection_reason,
    )
    # Mirror merged gate onto analysis used for status decision.
    analysis = analysis.model_copy(
        update={
            "requires_public_social_action": entry.requires_public_social_action,
            "entry_acceptable": entry.entry_acceptable,
            "entry_rejection_reason": entry.entry_rejection_reason,
        }
    )

    status = decide_status(
        analysis,
        entry_url_status=giveaway.entry_url_status,
    )
    prize_value = (
        Decimal(str(analysis.estimated_prize_value_eur))
        if analysis.estimated_prize_value_eur is not None
        else None
    )
    return repo.save_analysis(
        giveaway.id,
        analysis_json=analysis_to_json(analysis, model=model),
        status=status,
        confidence=analysis.confidence,
        title=analysis.title or giveaway.title,
        description=analysis.summary,
        prize=analysis.prize,
        prize_value_eur=prize_value,
        prize_category=analysis.prize_category.value,
        wanted_prize=analysis.wanted_prize,
        prize_priority=analysis.prize_priority,
        preference_reason=analysis.preference_reason,
        requires_travel=analysis.requires_travel,
        requires_additional_spend=analysis.requires_additional_spend,
        free_entry=analysis.free_entry,
        eligible_france=eligible_france,
        france_eligibility=france.value,
        eligibility_reason=analysis.eligibility_reason,
        eligible_countries=list(analysis.eligible_countries),
        excluded_countries=list(analysis.excluded_countries),
        requires_purchase=analysis.requires_purchase,
        requires_social=analysis.requires_social,
        entry_method=analysis.entry_method.value,
        requires_public_social_action=entry.requires_public_social_action,
        entry_acceptable=entry.entry_acceptable,
        entry_rejection_reason=entry.entry_rejection_reason,
        start_at=analysis.start_date,
        end_at=analysis.end_date,
        terms_url=analysis.terms_url,
        entry_url=analysis.entry_url,
    )


def mark_expired_without_gemini(repo: GiveawayRepository, giveaway: Giveaway) -> Giveaway:
    assert giveaway.id is not None
    payload = {
        "is_giveaway": True,
        "rejection_reason": None,
        "summary": "Marked expired locally before Gemini (clear expiry evidence).",
        "confidence": giveaway.confidence or 0.0,
        "_meta": {"model": None, "local_skip": "clearly_expired"},
    }
    # Do NOT set analyzed_at — that flag is reserved for successful Gemini results.
    return repo.apply_local_skip(
        giveaway.id,
        analysis_json=payload,
        status=GiveawayStatus.EXPIRED,
        confidence=giveaway.confidence,
    )


def mark_heuristic_rejected(repo: GiveawayRepository, giveaway: Giveaway) -> Giveaway:
    assert giveaway.id is not None
    payload = {
        "is_giveaway": False,
        "rejection_reason": "Failed local heuristic re-score; Gemini skipped.",
        "confidence": 0.0,
        "_meta": {"model": None, "local_skip": "heuristic_rejected"},
    }
    return repo.apply_local_skip(
        giveaway.id,
        analysis_json=payload,
        status=GiveawayStatus.REJECTED,
        confidence=0.0,
    )


def mark_undesirable_without_gemini(repo: GiveawayRepository, giveaway: Giveaway) -> Giveaway:
    assert giveaway.id is not None
    payload = {
        "is_giveaway": True,
        "rejection_reason": "Deterministic undesirable signals (paid/gambling/crypto/adult/etc).",
        "confidence": 0.0,
        "_meta": {"model": None, "local_skip": "undesirable"},
    }
    return repo.apply_local_skip(
        giveaway.id,
        analysis_json=payload,
        status=GiveawayStatus.REJECTED,
        confidence=0.0,
    )


def mark_france_ineligible_without_gemini(
    repo: GiveawayRepository,
    giveaway: Giveaway,
) -> Giveaway:
    assert giveaway.id is not None
    local = classify_france_eligibility(
        title=giveaway.title,
        prize=giveaway.prize,
        body=giveaway.raw_excerpt,
        restriction=giveaway.geo_restriction,
    )
    payload = {
        "is_giveaway": True,
        "rejection_reason": "France ineligible (local geo classification).",
        "france_eligibility": local.france_eligibility.value,
        "eligibility_reason": local.reason,
        "eligible_france": False,
        "confidence": 0.0,
        "_meta": {"model": None, "local_skip": "france_ineligible"},
    }
    return repo.apply_local_skip(
        giveaway.id,
        analysis_json=payload,
        status=GiveawayStatus.REJECTED,
        confidence=0.0,
        eligible_france=False,
        france_eligibility=local.france_eligibility.value,
        eligibility_reason=local.reason,
    )


def mark_public_social_without_gemini(
    repo: GiveawayRepository,
    giveaway: Giveaway,
) -> Giveaway:
    assert giveaway.id is not None
    requirements: list[str] = []
    platform_actions: list[dict[str, Any]] = []
    actions_required: int | None = None
    if isinstance(giveaway.analysis_json, dict):
        raw_req = giveaway.analysis_json.get("requirements")
        if isinstance(raw_req, list):
            requirements = [str(r) for r in raw_req if r]
        from app.extraction.entry_acceptability_backfill import (
            _actions_required_from_analysis,
            _platform_actions_from_analysis,
        )

        platform_actions = _platform_actions_from_analysis(giveaway.analysis_json)
        actions_required = _actions_required_from_analysis(giveaway.analysis_json)
    local = assess_entry_acceptability(
        title=giveaway.title,
        prize=giveaway.prize,
        body=giveaway.raw_excerpt,
        entry_method=giveaway.entry_method,
        requirements=requirements,
        platform_actions=platform_actions or None,
        actions_required=actions_required,
    )
    payload = {
        "is_giveaway": True,
        "rejection_reason": local.entry_rejection_reason or ENTRY_SOCIAL_REJECTION,
        "requires_public_social_action": True,
        "entry_acceptable": False,
        "entry_rejection_reason": local.entry_rejection_reason or ENTRY_SOCIAL_REJECTION,
        "confidence": 0.0,
        "_meta": {"model": None, "local_skip": "public_social"},
    }
    return repo.apply_local_skip(
        giveaway.id,
        analysis_json=payload,
        status=GiveawayStatus.REJECTED,
        confidence=0.0,
        requires_public_social_action=True,
        entry_acceptable=False,
        entry_rejection_reason=local.entry_rejection_reason or ENTRY_SOCIAL_REJECTION,
    )


def map_batch_items_by_id(
    *,
    expected_ids: set[UUID],
    items: list[GiveawayBatchItemAnalysis],
) -> tuple[dict[UUID, GiveawayBatchItemAnalysis], set[UUID], list[str]]:
    """
    Map Gemini batch items by giveaway_id (never by list index).

    Returns (valid_by_id, missing_ids, rejection_messages).
    Unknown / duplicate IDs are rejected and not applied.
    """
    valid: dict[UUID, GiveawayBatchItemAnalysis] = {}
    messages: list[str] = []
    for item in items:
        gid = item.giveaway_id
        if gid not in expected_ids:
            messages.append(f"unknown giveaway_id={gid}")
            continue
        if gid in valid:
            messages.append(f"duplicate giveaway_id={gid}")
            # Drop both the previous and this duplicate to be safe.
            del valid[gid]
            continue
        valid[gid] = item
    missing = set(expected_ids) - set(valid)
    return valid, missing, messages


def _record_status_counts(result: AnalyzeBatchResult, status: GiveawayStatus) -> None:
    if status == GiveawayStatus.REJECTED:
        result.rejected += 1
    elif status == GiveawayStatus.UNCERTAIN:
        result.uncertain += 1
    elif status == GiveawayStatus.EXPIRED:
        result.expired += 1
    elif status == GiveawayStatus.ACTIVE:
        result.confirmed += 1


def _apply_gemini_chunk(
    *,
    repo: GiveawayRepository,
    conn: Connection,
    gemini: GeminiClient,
    chunk: list[Giveaway],
    result: AnalyzeBatchResult,
) -> None:
    """Send one micro-batch; persist valid rows; leave missing/invalid pending."""
    by_id = {g.id: g for g in chunk if g.id is not None}
    expected_ids = set(by_id)
    inputs = [
        GiveawayPageInput(
            giveaway_id=g.id,  # type: ignore[arg-type]
            url=str(g.canonical_url),
            title=g.title,
            text=g.raw_excerpt,
            links=list(g.link_hints or []),
        )
        for g in chunk
    ]

    try:
        api: GeminiBatchResult = gemini.analyze_giveaway_batch(inputs)
        result.api_requests += 1
    except Exception as exc:
        conn.rollback()
        logger.exception(
            "analyze batch failed size=%s ids=%s",
            len(chunk),
            ",".join(str(i) for i in expected_ids),
        )
        result.errors += len(chunk)
        for giveaway in chunk:
            assert giveaway.id is not None
            result.items.append(
                AnalyzeItemResult(
                    giveaway_id=giveaway.id,
                    canonical_url=str(giveaway.canonical_url),
                    skipped=False,
                    error=f"{type(exc).__name__}: {exc}"[:500],
                    pending=True,
                )
            )
            result.pending += 1
        return

    valid, missing, messages = map_batch_items_by_id(
        expected_ids=expected_ids,
        items=list(api.items),
    )
    for msg in messages:
        logger.warning("gemini batch mapping: %s", msg)
        result.errors += 1

    for gid, item in valid.items():
        giveaway = by_id[gid]
        try:
            analysis = item.as_analysis()
            updated = apply_analysis(repo, giveaway, analysis, model=api.model)
            conn.commit()
            result.analyzed += 1
            _record_status_counts(result, updated.status)
            result.items.append(
                AnalyzeItemResult(
                    giveaway_id=gid,
                    canonical_url=str(giveaway.canonical_url),
                    skipped=False,
                    status=updated.status,
                    is_giveaway=analysis.is_giveaway,
                    confidence=analysis.confidence,
                    analysis=analysis,
                )
            )
        except Exception as exc:
            conn.rollback()
            logger.exception("analyze persist failed giveaway_id=%s", gid)
            result.errors += 1
            result.pending += 1
            result.items.append(
                AnalyzeItemResult(
                    giveaway_id=gid,
                    canonical_url=str(giveaway.canonical_url),
                    skipped=False,
                    error=f"{type(exc).__name__}: {exc}"[:500],
                    pending=True,
                )
            )

    for gid in missing:
        giveaway = by_id[gid]
        logger.warning(
            "gemini batch missing giveaway_id=%s — leaving pending (no immediate resend)",
            gid,
        )
        result.pending += 1
        result.items.append(
            AnalyzeItemResult(
                giveaway_id=gid,
                canonical_url=str(giveaway.canonical_url),
                skipped=False,
                pending=True,
                error="missing_from_batch_response",
            )
        )


def analyze_giveaways(
    conn: Connection,
    settings: Settings,
    *,
    client: GeminiClient | None = None,
    limit: int = 50,
    giveaway_id: UUID | None = None,
    giveaway_ids: list[UUID] | None = None,
    reanalyze: bool = False,
    dry_run: bool = False,
) -> AnalyzeBatchResult:
    """
    Analyze pending giveaways with Gemini micro-batches.

    `--limit` caps giveaways processed/attempted, not API request count.
    dry_run: list what would be sent; does not call Gemini and does not write.

    analyzed_at is set ONLY after a validated Gemini result is persisted.
    API failures leave rows pending (analyzed_at NULL, status candidate).
    """
    repo = GiveawayRepository(conn)
    result = AnalyzeBatchResult()
    batch_size = settings.gemini_batch_size

    if giveaway_id is not None and giveaway_ids is not None:
        raise ValueError("Pass giveaway_id or giveaway_ids, not both")

    if giveaway_id is not None:
        row = repo.get_by_id(giveaway_id)
        targets = [row] if row else []
        if not targets:
            raise LookupError(f"Giveaway not found: {giveaway_id}")
    elif giveaway_ids is not None:
        targets = []
        for gid in giveaway_ids[:limit]:
            row = repo.get_by_id(gid)
            if row is None:
                raise LookupError(f"Giveaway not found: {gid}")
            targets.append(row)
    else:
        targets = repo.list_for_analysis(limit=limit, include_analyzed=reanalyze)

    gemini = None if dry_run else (client or GeminiClient(settings))
    pending_for_gemini: list[Giveaway] = []

    for giveaway in targets:
        assert giveaway.id is not None
        result.processed += 1
        skip = should_skip_analysis(giveaway, settings=settings, reanalyze=reanalyze)
        if skip is not None:
            result.skipped += 1
            item = AnalyzeItemResult(
                giveaway_id=giveaway.id,
                canonical_url=str(giveaway.canonical_url),
                skipped=True,
                skip_reason=skip,
            )
            if not dry_run:
                if skip == SkipReason.CLEARLY_EXPIRED:
                    updated = mark_expired_without_gemini(repo, giveaway)
                    item.status = updated.status
                    item.is_giveaway = True
                    result.expired += 1
                    conn.commit()
                elif skip == SkipReason.HEURISTIC_REJECTED:
                    updated = mark_heuristic_rejected(repo, giveaway)
                    item.status = updated.status
                    item.is_giveaway = False
                    result.rejected += 1
                    conn.commit()
                elif skip == SkipReason.UNDESIRABLE:
                    updated = mark_undesirable_without_gemini(repo, giveaway)
                    item.status = updated.status
                    item.is_giveaway = True
                    result.rejected += 1
                    conn.commit()
                elif skip == SkipReason.FRANCE_INELIGIBLE:
                    updated = mark_france_ineligible_without_gemini(repo, giveaway)
                    item.status = updated.status
                    item.is_giveaway = True
                    result.rejected += 1
                    conn.commit()
                elif skip == SkipReason.PUBLIC_SOCIAL:
                    updated = mark_public_social_without_gemini(repo, giveaway)
                    item.status = updated.status
                    item.is_giveaway = True
                    result.rejected += 1
                    conn.commit()
            result.items.append(item)
            continue

        if dry_run:
            result.items.append(
                AnalyzeItemResult(
                    giveaway_id=giveaway.id,
                    canonical_url=str(giveaway.canonical_url),
                    skipped=False,
                )
            )
            continue

        pending_for_gemini.append(giveaway)

    if dry_run or not pending_for_gemini:
        return result

    assert gemini is not None
    # Process one Gemini micro-batch at a time (Pi memory: ~batch_size excerpts).
    for offset in range(0, len(pending_for_gemini), batch_size):
        chunk = pending_for_gemini[offset : offset + batch_size]
        _apply_gemini_chunk(
            repo=repo,
            conn=conn,
            gemini=gemini,
            chunk=chunk,
            result=result,
        )
        # Drop references to finished excerpts promptly.
        chunk.clear()

    return result


@dataclass(slots=True)
class AnalyzeAllResult:
    pending_at_start: int
    batch_count: int
    result: AnalyzeBatchResult


def _merge_analyze_results(into: AnalyzeBatchResult, src: AnalyzeBatchResult) -> None:
    into.processed += src.processed
    into.analyzed += src.analyzed
    into.skipped += src.skipped
    into.confirmed += src.confirmed
    into.rejected += src.rejected
    into.uncertain += src.uncertain
    into.expired += src.expired
    into.errors += src.errors
    into.api_requests += src.api_requests
    into.pending += src.pending
    into.items.extend(src.items)


def analyze_all_pending(
    conn: Connection,
    settings: Settings,
    *,
    client: GeminiClient | None = None,
    reanalyze: bool = False,
    dry_run: bool = False,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    only_ids: list[UUID] | None = None,
) -> AnalyzeAllResult:
    """
    Drain the pending Gemini queue in one process.

    - Fetches at most GEMINI_BATCH_SIZE rows from Neon per iteration.
    - Reuses a single GeminiClient (same RPM limiter) for the whole run.
    - Successful rows leave the queue; failed/skipped rows are excluded from
      further attempts in this run (no infinite retry of the same failure).
    - only_ids: optional allow-list (tests / scoped drains).
    """
    repo = GiveawayRepository(conn)
    batch_size = settings.gemini_batch_size
    # One client for the entire drain — never recreate (preserves RPM limiter).
    gemini = None if dry_run else (client or GeminiClient(settings))

    pending_at_start = repo.count_pending_analysis(
        include_analyzed=reanalyze,
        only_ids=only_ids,
    )
    if on_progress is not None:
        on_progress({"event": "start", "pending": pending_at_start})

    aggregated = AnalyzeBatchResult()
    exclude: set[UUID] = set()
    batch_num = 0

    while True:
        chunk = repo.list_for_analysis(
            limit=batch_size,
            include_analyzed=reanalyze,
            exclude_ids=list(exclude) if exclude else None,
            only_ids=only_ids,
        )
        if not chunk:
            break

        batch_num += 1
        ids = [g.id for g in chunk if g.id is not None]
        # Free listing references before re-load inside analyze_giveaways.
        chunk.clear()

        batch = analyze_giveaways(
            conn,
            settings,
            client=gemini,
            giveaway_ids=ids,
            limit=len(ids),
            reanalyze=reanalyze,
            dry_run=dry_run,
        )
        _merge_analyze_results(aggregated, batch)

        for item in batch.items:
            # Do not retry failures, pending leftovers, or skips in this run.
            if item.error or item.pending or item.skipped or dry_run:
                exclude.add(item.giveaway_id)

        remaining = repo.count_pending_analysis(
            include_analyzed=reanalyze,
            exclude_ids=list(exclude) if exclude else None,
            only_ids=only_ids,
        )
        if on_progress is not None:
            on_progress(
                {
                    "event": "batch",
                    "batch": batch_num,
                    "analyzed": batch.analyzed,
                    "remaining": remaining,
                }
            )

    if on_progress is not None:
        on_progress({"event": "done"})

    return AnalyzeAllResult(
        pending_at_start=pending_at_start,
        batch_count=batch_num,
        result=aggregated,
    )
