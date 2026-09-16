"""Local pre-checks to avoid unnecessary Gemini calls."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from app.extraction.entry_assessment import detect_undesirable
from app.models.giveaway import Giveaway
from app.scraping.scoring import score_candidate

# Explicit "already over" language — conservative; prefer missing a skip over a false skip.
_EXPIRED_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bconcours\s+termin[ée]\b",
        r"\bgiveaway\s+has\s+ended\b",
        r"\bthis\s+(giveaway|contest|sweepstakes|competition)\s+(has\s+)?(ended|closed)\b",
        r"\bthis\s+competition\s+has\s+closed\b",
        r"\bwinners?\s+have\s+(already\s+)?been\s+announced\b",
        r"\bgagnants?\s+(ont\s+été|deja|déjà)\s+d[ée]sign",
        r"\bclosed\s+giveaway\b",
        r"\binscriptions?\s+closes?\b.{0,40}\b(ago|passée|passees|passées)\b",
    )
)

_ISO_DATE = re.compile(
    r"\b(20\d{2})[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])\b"
)


def heuristic_below_threshold(giveaway: Giveaway, *, threshold: float) -> bool:
    """Re-score stored text; True if it would no longer pass the local candidate gate."""
    scored = score_candidate(
        url=str(giveaway.canonical_url),
        title=giveaway.title or "",
        content=giveaway.raw_excerpt or "",
    )
    return scored.score < threshold


def looks_clearly_expired(giveaway: Giveaway, *, now: datetime | None = None) -> bool:
    """
    Return True only when local evidence strongly indicates the giveaway is over.

    Used to skip Gemini. Prefer false negatives (call Gemini) over false positives.
    """
    at = now or datetime.now(UTC)
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)

    if giveaway.end_at is not None:
        end = giveaway.end_at
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        if end < at:
            return True

    blob = f"{giveaway.title or ''}\n{giveaway.raw_excerpt or ''}"
    if any(p.search(blob) for p in _EXPIRED_PATTERNS):
        return True

    ended_on = re.search(
        r"(?:ended on|clos(?:ed|es) on|terminé le|termine le|fin le)\s*[:=]?\s*"
        r"(20\d{2}[-/]0[1-9]|20\d{2}[-/]1[0-2])[-/](0[1-9]|[12]\d|3[01])",
        blob,
        re.IGNORECASE,
    )
    if ended_on:
        raw = re.search(_ISO_DATE, ended_on.group(0))
        if raw:
            try:
                y, m, d = map(int, raw.groups())
                if datetime(y, m, d, tzinfo=UTC) < at:
                    return True
            except ValueError:
                pass

    return False


def looks_undesirable_for_gemini(giveaway: Giveaway) -> bool:
    """Deterministic paid/gambling/crypto/postal/referral/survey skips."""
    if giveaway.requires_purchase is True:
        return True
    if giveaway.free_entry is False:
        return True
    reasons = detect_undesirable(title=giveaway.title, body=giveaway.raw_excerpt)
    return bool(
        set(reasons)
        & {
            "purchase_required",
            "paid_entry",
            "postal_only",
            "referrals",
            "casino",
            "gambling",
            "lottery",
            "crypto",
            "survey",
            "expired",
        }
    )
