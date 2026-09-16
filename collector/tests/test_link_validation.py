"""Entry URL HTTP classification and link-check persistence (no live network)."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from app.models.giveaway import Giveaway, GiveawayStatus
from app.validation.links import (
    EntryUrlStatus,
    LinkCheckResult,
    apply_link_check,
    classify_http_status,
)


def test_classify_http_status_matrix() -> None:
    assert classify_http_status(200).entry_url_status == EntryUrlStatus.LIVE
    assert classify_http_status(302).entry_url_status == EntryUrlStatus.LIVE
    assert classify_http_status(404).entry_url_status == EntryUrlStatus.GONE
    assert classify_http_status(410).entry_url_status == EntryUrlStatus.GONE
    assert classify_http_status(500).entry_url_status == EntryUrlStatus.TEMPORARY_ERROR
    assert classify_http_status(503).entry_url_status == EntryUrlStatus.TEMPORARY_ERROR
    blocked = classify_http_status(403)
    assert blocked.entry_url_status == EntryUrlStatus.BLOCKED
    assert blocked.entry_url_status != EntryUrlStatus.GONE
    rate = classify_http_status(429)
    assert rate.entry_url_status == EntryUrlStatus.TEMPORARY_ERROR
    assert rate.error == "rate_limited"
    net = classify_http_status(None, error="timeout")
    assert net.entry_url_status == EntryUrlStatus.TEMPORARY_ERROR


def test_apply_link_check_500_does_not_reject_first_time() -> None:
    giveaway = Giveaway(
        id=uuid4(),
        canonical_url="https://brand.example/g",
        original_url="https://brand.example/g",
        domain="brand.example",
        content_hash="abc",
        status=GiveawayStatus.ACTIVE,
        entry_fail_count=0,
        entry_url="https://brand.example/enter",
    )
    repo = MagicMock()
    repo.save_entry_validation.return_value = giveaway

    result = LinkCheckResult(EntryUrlStatus.TEMPORARY_ERROR, 500)
    apply_link_check(repo, giveaway, result)

    kwargs = repo.save_entry_validation.call_args.kwargs
    assert kwargs["entry_url_status"] == EntryUrlStatus.TEMPORARY_ERROR.value
    assert kwargs["entry_http_status"] == 500
    assert kwargs["entry_fail_count"] == 1
    assert kwargs["status"] is None


def test_apply_link_check_404_rejects() -> None:
    giveaway = Giveaway(
        id=uuid4(),
        canonical_url="https://brand.example/gone",
        original_url="https://brand.example/gone",
        domain="brand.example",
        content_hash="abc",
        status=GiveawayStatus.ACTIVE,
        entry_fail_count=0,
        entry_url="https://brand.example/enter",
    )
    repo = MagicMock()
    repo.save_entry_validation.return_value = giveaway

    result = LinkCheckResult(EntryUrlStatus.GONE, 404)
    apply_link_check(repo, giveaway, result)

    kwargs = repo.save_entry_validation.call_args.kwargs
    assert kwargs["entry_url_status"] == EntryUrlStatus.GONE.value
    assert kwargs["status"] == GiveawayStatus.REJECTED


def test_france_ps5_404_rejects_via_decide_status() -> None:
    from app.extraction.france_eligibility import FranceEligibility
    from app.gemini.schema import EntryMethod, GiveawayAnalysis
    from app.gemini.service import decide_status

    analysis = GiveawayAnalysis(
        is_giveaway=True,
        confidence=0.9,
        wanted_prize=True,
        prize="PS5",
        france_eligibility=FranceEligibility.ELIGIBLE,
        eligible_france=True,
        entry_method=EntryMethod.WEB_FORM,
        entry_acceptable=True,
        requires_public_social_action=False,
    )
    assert decide_status(analysis) == GiveawayStatus.ACTIVE
    assert decide_status(analysis, entry_url_status="gone") == GiveawayStatus.REJECTED
    assert (
        decide_status(analysis, entry_url_status="temporary_error") == GiveawayStatus.ACTIVE
    )
