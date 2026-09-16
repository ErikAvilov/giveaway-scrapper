"""Re-evaluate entry acceptability from stored crawl/analysis text (no re-crawl)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from psycopg import Connection

from app.db.repository import GiveawayRepository
from app.extraction.entry_acceptability import (
    REJECTION_REASON,
    assess_entry_acceptability,
)
from app.models.giveaway import Giveaway, GiveawayStatus

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EntryAcceptabilityBackfillSummary:
    scanned: int = 0
    updated: int = 0
    rejected: int = 0
    acceptable: int = 0
    unknown: int = 0
    unchanged: int = 0


def _requirements_from_analysis(analysis: dict[str, Any] | None) -> list[str]:
    if not isinstance(analysis, dict):
        return []
    req = analysis.get("requirements")
    if isinstance(req, list):
        return [str(r) for r in req if r]
    return []


def _platform_actions_from_analysis(analysis: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(analysis, dict):
        return []
    actions: list[dict[str, Any]] = []
    for key, mandatory in (
        ("mandatory_actions", True),
        ("optional_actions", False),
    ):
        raw = analysis.get(key)
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and item.get("entry_type"):
                    actions.append(
                        {
                            "entry_type": item.get("entry_type"),
                            "mandatory": item.get("mandatory", mandatory),
                        }
                    )
                elif isinstance(item, str):
                    actions.append({"entry_type": item, "mandatory": mandatory})
    for et in analysis.get("mandatory_entry_types") or []:
        actions.append({"entry_type": et, "mandatory": True})
    for et in analysis.get("optional_entry_types") or []:
        actions.append({"entry_type": et, "mandatory": False})
    # Gleam-style lists sometimes nest under platform / adapter meta.
    meta = analysis.get("_meta") if isinstance(analysis.get("_meta"), dict) else {}
    for et in meta.get("mandatory_entry_types") or []:
        actions.append({"entry_type": et, "mandatory": True})
    return actions


def _body_blob(giveaway: Giveaway) -> str:
    parts: list[str] = []
    if giveaway.raw_excerpt:
        parts.append(giveaway.raw_excerpt)
    if giveaway.description:
        parts.append(giveaway.description)
    analysis = giveaway.analysis_json if isinstance(giveaway.analysis_json, dict) else None
    if analysis:
        for key in ("summary", "eligibility_notes", "entry_method"):
            val = analysis.get(key)
            if isinstance(val, str) and val.strip():
                parts.append(val)
        parts.extend(_requirements_from_analysis(analysis))
    return "\n".join(parts)


def assess_giveaway_entry_acceptability(giveaway: Giveaway):
    analysis = giveaway.analysis_json if isinstance(giveaway.analysis_json, dict) else None
    return assess_entry_acceptability(
        title=giveaway.title,
        prize=giveaway.prize,
        body=_body_blob(giveaway),
        entry_method=giveaway.entry_method,
        requirements=_requirements_from_analysis(analysis),
        platform_actions=_platform_actions_from_analysis(analysis) or None,
    )


def backfill_entry_acceptability(
    conn: Connection,
    *,
    limit: int = 500,
    force: bool = False,
    dry_run: bool = False,
) -> EntryAcceptabilityBackfillSummary:
    """
    Fill requires_public_social_action / entry_acceptable from stored text.

    When force=False, only rows with entry_acceptable IS NULL.
    Rejected public-social rows get status=rejected when currently active/candidate.
    """
    repo = GiveawayRepository(conn)
    summary = EntryAcceptabilityBackfillSummary()
    rows = repo.list_for_entry_acceptability_backfill(limit=limit, force=force)
    for giveaway in rows:
        assert giveaway.id is not None
        summary.scanned += 1
        gate = assess_giveaway_entry_acceptability(giveaway)
        same = (
            giveaway.requires_public_social_action == gate.requires_public_social_action
            and giveaway.entry_acceptable == gate.entry_acceptable
            and (giveaway.entry_rejection_reason or None)
            == (gate.entry_rejection_reason or None)
        )
        if same and not force:
            summary.unchanged += 1
            continue

        new_status: GiveawayStatus | str | None = None
        if gate.entry_acceptable is False:
            summary.rejected += 1
            if giveaway.status in {
                GiveawayStatus.ACTIVE,
                GiveawayStatus.CANDIDATE,
                GiveawayStatus.UNCERTAIN,
            }:
                new_status = GiveawayStatus.REJECTED
        elif gate.entry_acceptable is True:
            summary.acceptable += 1
        else:
            summary.unknown += 1

        if dry_run:
            summary.updated += 1
            continue

        repo.save_entry_acceptability(
            giveaway.id,
            requires_public_social_action=gate.requires_public_social_action,
            entry_acceptable=gate.entry_acceptable,
            entry_rejection_reason=gate.entry_rejection_reason
            or (REJECTION_REASON if gate.entry_acceptable is False else None),
            status=new_status,
        )
        summary.updated += 1

    logger.info(
        "entry_acceptability backfill scanned=%s updated=%s rejected=%s "
        "acceptable=%s unknown=%s dry_run=%s",
        summary.scanned,
        summary.updated,
        summary.rejected,
        summary.acceptable,
        summary.unknown,
        dry_run,
    )
    return summary
