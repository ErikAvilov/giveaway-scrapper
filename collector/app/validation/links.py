"""HTTP entry-URL validation (Scrapling FetcherSession, no browser)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from psycopg import Connection

from app.config import Settings
from app.db.repository import GiveawayRepository
from app.models.giveaway import Giveaway, GiveawayStatus

logger = logging.getLogger(__name__)

# Mark permanently gone only after this many consecutive temp failures.
TEMP_FAIL_THRESHOLD = 3


class EntryUrlStatus(StrEnum):
    LIVE = "live"
    GONE = "gone"
    TEMPORARY_ERROR = "temporary_error"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


@dataclass(slots=True, frozen=True)
class LinkCheckResult:
    entry_url_status: EntryUrlStatus
    entry_http_status: int | None
    error: str | None = None


@dataclass(slots=True)
class ValidateLinksResult:
    checked: int = 0
    live: int = 0
    gone: int = 0
    temporary_error: int = 0
    blocked: int = 0
    unknown: int = 0
    rejected: int = 0
    errors: int = 0


def classify_http_status(status_code: int | None, *, error: str | None = None) -> LinkCheckResult:
    if status_code is None:
        return LinkCheckResult(EntryUrlStatus.TEMPORARY_ERROR, None, error or "network_error")
    if 200 <= status_code < 400:
        return LinkCheckResult(EntryUrlStatus.LIVE, status_code)
    if status_code in {404, 410}:
        return LinkCheckResult(EntryUrlStatus.GONE, status_code)
    if status_code in {401, 403}:
        return LinkCheckResult(EntryUrlStatus.BLOCKED, status_code)
    if status_code == 429:
        return LinkCheckResult(EntryUrlStatus.TEMPORARY_ERROR, status_code, "rate_limited")
    if 500 <= status_code <= 599:
        return LinkCheckResult(EntryUrlStatus.TEMPORARY_ERROR, status_code)
    return LinkCheckResult(EntryUrlStatus.UNKNOWN, status_code)


def check_entry_url(url: str, *, timeout: float = 20.0) -> LinkCheckResult:
    """
    HEAD then GET fallback via Scrapling FetcherSession (chrome impersonation).
    Follows redirects; does not bypass blocks.
    """
    try:
        from scrapling.fetchers import FetcherSession
    except ImportError:  # pragma: no cover
        return LinkCheckResult(EntryUrlStatus.UNKNOWN, None, "scrapling_unavailable")

    session = FetcherSession(
        impersonate="chrome",
        timeout=int(timeout),
        retries=1,
        retry_delay=1,
        stealthy_headers=True,
    )
    try:
        # Prefer GET — many hosts reject HEAD.
        response = session.get(url, allow_redirects=True)
        status = getattr(response, "status", None) or getattr(response, "status_code", None)
        if status is None and hasattr(response, "raw"):
            status = getattr(response.raw, "status", None)
        return classify_http_status(int(status) if status is not None else None)
    except Exception as exc:  # noqa: BLE001 — network stack varies
        msg = str(exc).lower()
        if "429" in msg or "rate" in msg:
            return LinkCheckResult(EntryUrlStatus.TEMPORARY_ERROR, 429, "rate_limited")
        if "403" in msg or "401" in msg or "forbidden" in msg:
            code = 403 if "403" in msg or "forbidden" in msg else 401
            return LinkCheckResult(EntryUrlStatus.BLOCKED, code, str(exc)[:200])
        if "404" in msg:
            return LinkCheckResult(EntryUrlStatus.GONE, 404, str(exc)[:200])
        return LinkCheckResult(EntryUrlStatus.TEMPORARY_ERROR, None, str(exc)[:200])


def apply_link_check(
    repo: GiveawayRepository,
    giveaway: Giveaway,
    result: LinkCheckResult,
    *,
    temp_fail_threshold: int = TEMP_FAIL_THRESHOLD,
) -> Giveaway:
    assert giveaway.id is not None
    prev_fails = int(getattr(giveaway, "entry_fail_count", 0) or 0)
    status = result.entry_url_status
    fail_count = prev_fails

    if status == EntryUrlStatus.LIVE:
        fail_count = 0
    elif status in {EntryUrlStatus.TEMPORARY_ERROR, EntryUrlStatus.GONE}:
        fail_count = prev_fails + 1

    # Never permanently reject on first 5xx / network failure.
    effective = status
    if status == EntryUrlStatus.TEMPORARY_ERROR and fail_count < temp_fail_threshold:
        effective = EntryUrlStatus.TEMPORARY_ERROR
    elif status == EntryUrlStatus.TEMPORARY_ERROR and fail_count >= temp_fail_threshold:
        # Still temporary_error in column, but leave status as-is (do not auto-gone).
        effective = EntryUrlStatus.TEMPORARY_ERROR

    new_status: GiveawayStatus | None = None
    if status == EntryUrlStatus.GONE:
        new_status = GiveawayStatus.REJECTED

    return repo.save_entry_validation(
        giveaway.id,
        entry_url_status=effective.value,
        entry_http_status=result.entry_http_status,
        entry_fail_count=fail_count,
        entry_checked_at=datetime.now(UTC),
        status=new_status,
    )


def validate_giveaway_links(
    conn: Connection[Any],
    settings: Settings,
    *,
    limit: int = 50,
    all_pending: bool = False,
    only_unchecked: bool = False,
) -> ValidateLinksResult:
    """Validate entry URLs in bounded batches (never loads full table)."""
    del settings  # reserved for future rate limits
    repo = GiveawayRepository(conn)
    out = ValidateLinksResult()
    batch = max(1, min(limit, 100))
    checked_ids: set[UUID] = set()
    max_rounds = 10_000 if all_pending else 1
    rounds = 0

    while rounds < max_rounds:
        rounds += 1
        rows = repo.list_for_link_validation(
            limit=batch,
            exclude_ids=list(checked_ids) or None,
            only_unchecked=only_unchecked,
        )
        if not rows:
            break
        for g in rows:
            assert g.id is not None
            checked_ids.add(g.id)
            url = (g.entry_url or str(g.canonical_url) or "").strip()
            if not url:
                out.unknown += 1
                out.checked += 1
                repo.save_entry_validation(
                    g.id,
                    entry_url_status=EntryUrlStatus.UNKNOWN.value,
                    entry_http_status=None,
                    entry_fail_count=int(getattr(g, "entry_fail_count", 0) or 0),
                    entry_checked_at=datetime.now(UTC),
                )
                continue
            try:
                result = check_entry_url(url)
                updated = apply_link_check(repo, g, result)
                out.checked += 1
                st = EntryUrlStatus(updated.entry_url_status or result.entry_url_status.value)
                if st == EntryUrlStatus.LIVE:
                    out.live += 1
                elif st == EntryUrlStatus.GONE:
                    out.gone += 1
                    if updated.status == GiveawayStatus.REJECTED:
                        out.rejected += 1
                elif st == EntryUrlStatus.TEMPORARY_ERROR:
                    out.temporary_error += 1
                elif st == EntryUrlStatus.BLOCKED:
                    out.blocked += 1
                else:
                    out.unknown += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("link validation error id=%s err=%s", g.id, exc)
                out.errors += 1
                out.checked += 1
        conn.commit()
        if not all_pending:
            break
    return out
