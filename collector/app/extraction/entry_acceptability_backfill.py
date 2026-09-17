"""Re-evaluate entry acceptability from stored crawl/analysis metadata (no re-crawl)."""

from __future__ import annotations

import logging
import re
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
    restored: int = 0


def _requirements_from_analysis(analysis: dict[str, Any] | None) -> list[str]:
    if not isinstance(analysis, dict):
        return []
    req = analysis.get("requirements")
    if isinstance(req, list):
        return [str(r) for r in req if r]
    return []


def _actions_required_from_analysis(analysis: dict[str, Any] | None) -> int | None:
    if not isinstance(analysis, dict):
        return None
    for key in ("actions_required",):
        raw = analysis.get(key)
        if raw is not None:
            try:
                return max(0, int(raw))
            except (TypeError, ValueError):
                pass
    meta = analysis.get("_meta") if isinstance(analysis.get("_meta"), dict) else {}
    raw = meta.get("actions_required")
    if raw is not None:
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            pass
    return None


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
    meta = analysis.get("_meta") if isinstance(analysis.get("_meta"), dict) else {}
    for et in meta.get("mandatory_entry_types") or []:
        actions.append({"entry_type": et, "mandatory": True})
    for et in meta.get("optional_entry_types") or []:
        actions.append({"entry_type": et, "mandatory": False})
    for key, mandatory in (
        ("mandatory_actions", True),
        ("optional_actions", False),
    ):
        raw = meta.get(key)
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and item.get("entry_type"):
                    actions.append(
                        {
                            "entry_type": item.get("entry_type"),
                            "mandatory": item.get("mandatory", mandatory),
                        }
                    )
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


def _platform_actions_from_text(giveaway: Giveaway) -> list[dict[str, Any]]:
    """Recover Gleam-style action lists from entry_method / excerpt when JSON lacks them."""
    actions: list[dict[str, Any]] = []
    blobs = [giveaway.entry_method or "", giveaway.raw_excerpt or ""]
    analysis = giveaway.analysis_json if isinstance(giveaway.analysis_json, dict) else None
    if analysis:
        for key in ("entry_method", "summary"):
            val = analysis.get(key)
            if isinstance(val, str):
                blobs.append(val)

    for blob in blobs:
        if not blob:
            continue
        # "mandatory:email_subscribe,instagram_follow" or "mandatory:a,b"
        for mand_m in re.finditer(
            r"mandatory\s*:\s*([a-z0-9_,\-\s]+)", blob, flags=re.IGNORECASE
        ):
            for et in re.split(r"[\s,;]+", mand_m.group(1).strip()):
                et = et.strip().lower()
                if et and et not in {"required", "optional"}:
                    actions.append({"entry_type": et, "mandatory": True})
        for opt_m in re.finditer(
            r"optional\s*:\s*([a-z0-9_,\-\s]+)", blob, flags=re.IGNORECASE
        ):
            for et in re.split(r"[\s,;]+", opt_m.group(1).strip()):
                et = et.strip().lower()
                if et:
                    actions.append({"entry_type": et, "mandatory": False})
        for req_m in re.finditer(
            r"Required:\s*([a-z0-9_\-]+)", blob, flags=re.IGNORECASE
        ):
            actions.append({"entry_type": req_m.group(1).lower(), "mandatory": True})
        for opt_line in re.finditer(
            r"Optional:\s*([a-z0-9_\-]+)", blob, flags=re.IGNORECASE
        ):
            actions.append(
                {"entry_type": opt_line.group(1).lower(), "mandatory": False}
            )
    return actions


def _actions_required_from_text(giveaway: Giveaway) -> int | None:
    blobs = [giveaway.entry_method or "", giveaway.raw_excerpt or ""]
    for blob in blobs:
        m = re.search(r"actions_required\s*=\s*(\d+)", blob or "", flags=re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def assess_giveaway_entry_acceptability(giveaway: Giveaway):
    analysis = giveaway.analysis_json if isinstance(giveaway.analysis_json, dict) else None
    actions = _platform_actions_from_analysis(analysis)
    if not actions:
        actions = _platform_actions_from_text(giveaway)
    actions_required = _actions_required_from_analysis(analysis)
    if actions_required is None:
        actions_required = _actions_required_from_text(giveaway)
    return assess_entry_acceptability(
        title=giveaway.title,
        prize=giveaway.prize,
        body=_body_blob(giveaway),
        entry_method=giveaway.entry_method,
        requirements=_requirements_from_analysis(analysis),
        platform_actions=actions or None,
        actions_required=actions_required,
    )


def _is_public_social_rejection(giveaway: Giveaway) -> bool:
    reason = (giveaway.entry_rejection_reason or "").strip().lower()
    if REJECTION_REASON in reason:
        return True
    if "public social" in reason or "social-media" in reason:
        return True
    return (
        giveaway.entry_acceptable is False
        and giveaway.requires_public_social_action is True
    )


def _status_after_restore(giveaway: Giveaway) -> GiveawayStatus | None:
    """When clearing a faulty public-social reject, restore a sensible status."""
    if giveaway.status != GiveawayStatus.REJECTED:
        return None
    if giveaway.analyzed_at is not None:
        return GiveawayStatus.ACTIVE
    return GiveawayStatus.CANDIDATE


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


def reevaluate_entry_rules(
    conn: Connection,
    *,
    limit: int = 500,
    dry_run: bool = False,
) -> EntryAcceptabilityBackfillSummary:
    """
    Targeted re-evaluation of rows previously rejected for public-social reasons.

    Only revisits entry_acceptable=false with a public-social rejection signal.
    Preserves manual_status, analyzed_at, wanted_prize, France fields.
    Restores status from rejected → active/candidate when a clean path is found.
    """
    repo = GiveawayRepository(conn)
    summary = EntryAcceptabilityBackfillSummary()
    rows = repo.list_for_entry_rules_reevaluation(limit=limit)
    for giveaway in rows:
        assert giveaway.id is not None
        if not _is_public_social_rejection(giveaway):
            continue
        summary.scanned += 1
        gate = assess_giveaway_entry_acceptability(giveaway)
        same = (
            giveaway.requires_public_social_action == gate.requires_public_social_action
            and giveaway.entry_acceptable == gate.entry_acceptable
            and (giveaway.entry_rejection_reason or None)
            == (gate.entry_rejection_reason or None)
        )
        if same:
            summary.unchanged += 1
            continue

        new_status: GiveawayStatus | str | None = None
        if gate.entry_acceptable is True:
            summary.acceptable += 1
            restored = _status_after_restore(giveaway)
            if restored is not None:
                new_status = restored
                summary.restored += 1
        elif gate.entry_acceptable is False:
            summary.rejected += 1
        else:
            summary.unknown += 1
            # Ambiguous after reevaluation: clear hard reject but leave status.
            if giveaway.status == GiveawayStatus.REJECTED:
                new_status = _status_after_restore(giveaway)
                if new_status is not None:
                    summary.restored += 1

        if dry_run:
            summary.updated += 1
            continue

        # Clear rejection reason when now acceptable.
        reason = gate.entry_rejection_reason
        if gate.entry_acceptable is True:
            reason = None
        elif gate.entry_acceptable is False:
            reason = reason or REJECTION_REASON

        repo.save_entry_acceptability(
            giveaway.id,
            requires_public_social_action=gate.requires_public_social_action,
            entry_acceptable=gate.entry_acceptable,
            entry_rejection_reason=reason,
            status=new_status,
        )
        summary.updated += 1

    logger.info(
        "reevaluate_entry_rules scanned=%s updated=%s acceptable=%s "
        "rejected=%s restored=%s unknown=%s unchanged=%s dry_run=%s",
        summary.scanned,
        summary.updated,
        summary.acceptable,
        summary.rejected,
        summary.restored,
        summary.unknown,
        summary.unchanged,
        dry_run,
    )
    return summary
