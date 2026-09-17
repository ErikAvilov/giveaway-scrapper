"""Tests for non-public entry-path acceptability gate."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.db.connection import connection
from app.db.repository import GiveawayRepository
from app.extraction.entry_acceptability import (
    REJECTION_REASON,
    ActionClass,
    assess_entry_acceptability,
    assess_platform_actions,
    classify_action_type,
)
from app.extraction.entry_acceptability_backfill import (
    assess_giveaway_entry_acceptability,
    reevaluate_entry_rules,
)
from app.extraction.france_eligibility import FranceEligibility
from app.gemini.schema import EntryMethod, GiveawayAnalysis
from app.gemini.service import decide_status
from app.models.giveaway import GiveawayStatus, ManualStatus
from app.urls import canonicalize_url


def test_visit_follow_optional_comment_acceptable() -> None:
    gate = assess_entry_acceptability(
        platform_actions=[
            {"entry_type": "visit_website", "mandatory": False},
            {"entry_type": "instagram_follow", "mandatory": False},
            {"entry_type": "instagram_comment", "mandatory": False},
        ],
        actions_required=1,
    )
    assert gate.entry_acceptable is True
    assert gate.requires_public_social_action is False
    assert gate.has_non_public_entry_path is True


def test_email_optional_share_acceptable() -> None:
    gate = assess_entry_acceptability(
        platform_actions=[
            {"entry_type": "email_subscribe", "mandatory": True},
            {"entry_type": "instagram_story", "mandatory": False},
        ]
    )
    assert gate.entry_acceptable is True
    assert gate.requires_public_social_action is False


def test_follow_instagram_only_acceptable() -> None:
    gate = assess_entry_acceptability(
        platform_actions=[{"entry_type": "instagram_follow", "mandatory": True}]
    )
    assert gate.entry_acceptable is True
    assert gate.requires_public_social_action is False


def test_discord_visit_acceptable() -> None:
    gate = assess_entry_acceptability(
        platform_actions=[
            {"entry_type": "discord_join_server", "mandatory": True},
            {"entry_type": "visit_website", "mandatory": True},
        ]
    )
    assert gate.entry_acceptable is True


def test_mandatory_comment_and_tag_unacceptable() -> None:
    gate = assess_entry_acceptability(
        platform_actions=[
            {"entry_type": "instagram_comment", "mandatory": True},
            {"entry_type": "twitter_tweet", "mandatory": True},
        ]
    )
    assert gate.entry_acceptable is False
    assert gate.requires_public_social_action is True
    assert gate.entry_rejection_reason == REJECTION_REASON


def test_pick_n_enough_non_public_acceptable() -> None:
    # Case D: require 3 of 8, 4 non-public available
    actions = [
        {"entry_type": "visit_website", "mandatory": False},
        {"entry_type": "instagram_follow", "mandatory": False},
        {"entry_type": "email_subscribe", "mandatory": False},
        {"entry_type": "discord_join_server", "mandatory": False},
        {"entry_type": "instagram_comment", "mandatory": False},
        {"entry_type": "twitter_retweet", "mandatory": False},
        {"entry_type": "instagram_story", "mandatory": False},
        {"entry_type": "share_action", "mandatory": False},
    ]
    gate = assess_platform_actions(actions, actions_required=3)
    assert gate is not None
    assert gate.entry_acceptable is True
    assert gate.non_public_actions_available == 4


def test_pick_n_insufficient_non_public_unacceptable() -> None:
    # Case E: require 5, only 3 non-public
    actions = [
        {"entry_type": "visit_website", "mandatory": False},
        {"entry_type": "instagram_follow", "mandatory": False},
        {"entry_type": "email_subscribe", "mandatory": False},
        {"entry_type": "instagram_comment", "mandatory": False},
        {"entry_type": "twitter_retweet", "mandatory": False},
        {"entry_type": "instagram_story", "mandatory": False},
        {"entry_type": "share_action", "mandatory": False},
        {"entry_type": "facebook_share", "mandatory": False},
    ]
    gate = assess_platform_actions(actions, actions_required=5)
    assert gate is not None
    assert gate.entry_acceptable is False
    assert gate.requires_public_social_action is True


def test_optional_referral_does_not_reject() -> None:
    gate = assess_entry_acceptability(
        platform_actions=[
            {"entry_type": "email_subscribe", "mandatory": True},
            {"entry_type": "referral", "mandatory": False},
        ]
    )
    assert gate.entry_acceptable is True


def test_optional_share_to_story_does_not_reject() -> None:
    gate = assess_entry_acceptability(
        body="Email signup. Optional share to story for bonus entries.",
        platform_actions=[
            {"entry_type": "email_subscribe", "mandatory": True},
            {"entry_type": "instagram_story", "mandatory": False},
        ],
    )
    assert gate.entry_acceptable is True
    assert gate.public_social_actions_available is True


def test_unknown_action_alone_does_not_reject() -> None:
    gate = assess_entry_acceptability(
        platform_actions=[{"entry_type": "custom_mystery_widget", "mandatory": True}]
    )
    # Unknown alone → not an automatic reject
    assert gate.entry_acceptable is not False


def test_text_follow_acceptable_retweet_to_enter_rejects() -> None:
    assert assess_entry_acceptability(body="Follow us on Instagram").entry_acceptable is True
    assert (
        assess_entry_acceptability(body="Retweet to enter").entry_acceptable is False
    )


def test_classify_follow_vs_comment() -> None:
    assert classify_action_type("instagram_follow") == ActionClass.NON_PUBLIC
    assert classify_action_type("instagram_comment") == ActionClass.PUBLIC_SOCIAL
    assert classify_action_type("weird_xyz") == ActionClass.UNKNOWN


def test_decide_status_rejects_public_social() -> None:
    analysis = GiveawayAnalysis(
        is_giveaway=True,
        confidence=0.9,
        entry_method=EntryMethod.WEB_FORM,
        france_eligibility=FranceEligibility.ELIGIBLE,
        eligible_france=True,
        wanted_prize=True,
        requires_public_social_action=True,
        entry_acceptable=False,
        entry_rejection_reason=REJECTION_REASON,
    )
    assert decide_status(analysis) == GiveawayStatus.REJECTED


def test_decide_status_uncertain_when_entry_unknown() -> None:
    analysis = GiveawayAnalysis(
        is_giveaway=True,
        confidence=0.9,
        entry_method=EntryMethod.WEB_FORM,
        france_eligibility=FranceEligibility.ELIGIBLE,
        eligible_france=True,
        wanted_prize=True,
        entry_acceptable=None,
    )
    assert decide_status(analysis) == GiveawayStatus.UNCERTAIN


@pytest.fixture
def db_conn(settings, migrated_db):
    with connection(settings) as conn:
        yield conn


def test_previously_rejected_gleam_becomes_acceptable(db_conn, settings) -> None:
    del settings
    repo = GiveawayRepository(db_conn)
    url = f"https://gleam.io/pathTest/{uuid4().hex[:8]}"
    try:
        result = repo.upsert_from_crawl(
            url=url,
            title="PS5 giveaway",
            content_hash="h-entry-path",
            platform="gleam",
            platform_campaign_id="pathTest",
            entry_acceptable=False,
            requires_public_social_action=True,
            entry_rejection_reason=REJECTION_REASON,
            status=GiveawayStatus.REJECTED,
            wanted_prize=True,
            eligible_france=True,
        )
        assert result.giveaway.id is not None
        # Store Gleam-like action metadata (clean path + optional comment).
        repo.save_analysis(
            result.giveaway.id,
            analysis_json={
                "is_giveaway": True,
                "actions_required": 1,
                "mandatory_actions": [],
                "optional_actions": [
                    {"entry_type": "visit_website", "mandatory": False},
                    {"entry_type": "instagram_follow", "mandatory": False},
                    {"entry_type": "instagram_comment", "mandatory": False},
                ],
                "requires_public_social_action": True,
                "entry_acceptable": False,
                "entry_rejection_reason": REJECTION_REASON,
            },
            status=GiveawayStatus.REJECTED,
            confidence=0.8,
            wanted_prize=True,
            entry_acceptable=False,
            requires_public_social_action=True,
            entry_rejection_reason=REJECTION_REASON,
            eligible_france=True,
            france_eligibility="eligible",
        )
        # Keep an entered manual status to prove it is preserved.
        db_conn.execute(
            "UPDATE giveaways SET manual_status = %s WHERE id = %s",
            (ManualStatus.ENTERED.value, result.giveaway.id),
        )
        before = repo.get_by_id(result.giveaway.id)
        assert before is not None
        assert before.manual_status == ManualStatus.ENTERED
        analyzed_at = before.analyzed_at

        gate = assess_giveaway_entry_acceptability(before)
        assert gate.entry_acceptable is True

        summary = reevaluate_entry_rules(db_conn, limit=50, dry_run=False)
        assert summary.scanned >= 1
        after = repo.get_by_id(result.giveaway.id)
        assert after is not None
        assert after.entry_acceptable is True
        assert after.requires_public_social_action is False
        assert after.entry_rejection_reason is None
        assert after.manual_status == ManualStatus.ENTERED
        assert after.analyzed_at == analyzed_at
        assert after.wanted_prize is True
        # Entered rows that were rejected for social are restored to active.
        assert after.status == GiveawayStatus.ACTIVE
    finally:
        repo.delete_by_canonical_url(canonicalize_url(url))


def test_manual_status_unchanged_during_reevaluation(db_conn, settings) -> None:
    del settings
    repo = GiveawayRepository(db_conn)
    url = f"https://gleam.io/manualKeep/{uuid4().hex[:8]}"
    try:
        result = repo.upsert_from_crawl(
            url=url,
            title="Manual keep",
            content_hash="h-manual",
            platform="gleam",
            entry_acceptable=False,
            requires_public_social_action=True,
            entry_rejection_reason=REJECTION_REASON,
            status=GiveawayStatus.REJECTED,
        )
        assert result.giveaway.id is not None
        repo.save_analysis(
            result.giveaway.id,
            analysis_json={
                "optional_actions": [
                    {"entry_type": "email_subscribe", "mandatory": False},
                    {"entry_type": "twitter_retweet", "mandatory": False},
                ],
                "actions_required": 1,
                "entry_acceptable": False,
                "requires_public_social_action": True,
                "entry_rejection_reason": REJECTION_REASON,
            },
            status=GiveawayStatus.REJECTED,
            entry_acceptable=False,
            requires_public_social_action=True,
            entry_rejection_reason=REJECTION_REASON,
            analyzed_at=datetime.now(UTC),
        )
        db_conn.execute(
            "UPDATE giveaways SET manual_status = %s WHERE id = %s",
            (ManualStatus.IGNORED.value, result.giveaway.id),
        )
        reevaluate_entry_rules(db_conn, limit=20, dry_run=False)
        after = repo.get_by_id(result.giveaway.id)
        assert after is not None
        assert after.manual_status == ManualStatus.IGNORED
        assert after.entry_acceptable is True
    finally:
        repo.delete_by_canonical_url(canonicalize_url(url))
