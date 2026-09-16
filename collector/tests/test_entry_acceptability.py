"""Tests for public social-media entry acceptability gate."""

from __future__ import annotations

import pytest

from app.extraction.entry_acceptability import (
    REJECTION_REASON,
    assess_entry_acceptability,
    assess_platform_actions,
)
from app.extraction.france_eligibility import FranceEligibility
from app.gemini.schema import EntryMethod, GiveawayAnalysis
from app.gemini.service import decide_status
from app.models.giveaway import GiveawayStatus


@pytest.mark.parametrize(
    "text",
    [
        "Tag 3 friends on Instagram",
        "Comment below and mention a friend",
        "Share this post to your story",
        "Retweet to enter",
        "Post a photo with #Giveaway",
        "Taguez un ami et commentez",
        "Publiez en story pour participer",
        "Follow account + mandatory tag 2 friends",
    ],
)
def test_mandatory_public_social_unacceptable(text: str) -> None:
    gate = assess_entry_acceptability(body=text)
    assert gate.entry_acceptable is False
    assert gate.requires_public_social_action is True
    assert gate.entry_rejection_reason == REJECTION_REASON


@pytest.mark.parametrize(
    "text",
    [
        "Follow us on Instagram",
        "Subscribe to newsletter",
        "Email + name form",
        "Enter via Instagram form",
        "Create an account and log in",
        "Visit our webpage and answer a question",
        "Follow account + optional share for bonus entries",
        "Abonnez-vous à notre newsletter",
    ],
)
def test_non_public_or_optional_acceptable(text: str) -> None:
    gate = assess_entry_acceptability(body=text)
    assert gate.entry_acceptable is True
    assert gate.requires_public_social_action is False
    assert gate.entry_rejection_reason is None


def test_platform_mandatory_public_action() -> None:
    gate = assess_platform_actions(
        [
            {"entry_type": "instagram_follow", "mandatory": True},
            {"entry_type": "twitter_retweet", "mandatory": True},
        ]
    )
    assert gate is not None
    assert gate.entry_acceptable is False


def test_platform_optional_public_action_ignored() -> None:
    gate = assess_platform_actions(
        [
            {"entry_type": "email_subscribe", "mandatory": True},
            {"entry_type": "twitter_retweet", "mandatory": False},
        ]
    )
    assert gate is None
    full = assess_entry_acceptability(
        body="Follow us and enter your email",
        platform_actions=[
            {"entry_type": "email_subscribe", "mandatory": True},
            {"entry_type": "twitter_retweet", "mandatory": False},
        ],
    )
    assert full.entry_acceptable is True


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
