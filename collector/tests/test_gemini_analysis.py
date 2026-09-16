"""Unit tests for Gemini analysis helpers (mocked — no API credits)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from google.genai import errors as genai_errors

from app.gemini.client import GeminiAnalysisResult, GeminiClient, GeminiUsage, _is_retryable
from app.gemini.guards import looks_clearly_expired
from app.gemini.schema import EntryMethod, GiveawayAnalysis
from app.gemini.service import (
    SkipReason,
    decide_status,
    should_skip_analysis,
)
from app.models.giveaway import Giveaway, GiveawayStatus


def _giveaway(**kwargs: object) -> Giveaway:
    base = {
        "id": uuid4(),
        "canonical_url": "https://brand.example/concours/ete",
        "original_url": "https://brand.example/concours/ete?utm_source=x",
        "domain": "brand.example",
        "title": "Jeu concours — gagnez un cadeau",
        "content_hash": "abc",
        "raw_excerpt": (
            "Participez à notre jeu concours et remportez un cadeau. "
            "Tirage au sort. Date limite. Règlement du jeu. Pour participer."
        ),
        "status": GiveawayStatus.CANDIDATE,
    }
    base.update(kwargs)
    return Giveaway(**base)  # type: ignore[arg-type]


def test_decide_status_rejected() -> None:
    analysis = GiveawayAnalysis(
        is_giveaway=False,
        confidence=0.9,
        rejection_reason="Article about giveaways",
        entry_method=EntryMethod.UNKNOWN,
    )
    assert decide_status(analysis) == GiveawayStatus.REJECTED


def test_decide_status_expired_by_end_date() -> None:
    from app.extraction.france_eligibility import FranceEligibility

    analysis = GiveawayAnalysis(
        is_giveaway=True,
        confidence=0.9,
        end_date=datetime.now(UTC) - timedelta(days=2),
        entry_method=EntryMethod.WEB_FORM,
        france_eligibility=FranceEligibility.ELIGIBLE,
        eligible_france=True,
        wanted_prize=True,
        entry_acceptable=True,
        requires_public_social_action=False,
    )
    assert decide_status(analysis) == GiveawayStatus.EXPIRED


def test_decide_status_uncertain_low_confidence() -> None:
    from app.extraction.france_eligibility import FranceEligibility

    analysis = GiveawayAnalysis(
        is_giveaway=True,
        confidence=0.4,
        entry_method=EntryMethod.UNKNOWN,
        france_eligibility=FranceEligibility.ELIGIBLE,
        eligible_france=True,
        wanted_prize=True,
        entry_acceptable=True,
    )
    assert decide_status(analysis) == GiveawayStatus.UNCERTAIN


def test_decide_status_active() -> None:
    from app.extraction.france_eligibility import FranceEligibility

    analysis = GiveawayAnalysis(
        is_giveaway=True,
        confidence=0.8,
        end_date=datetime.now(UTC) + timedelta(days=10),
        entry_method=EntryMethod.WEB_FORM,
        france_eligibility=FranceEligibility.ELIGIBLE,
        eligible_france=True,
        wanted_prize=True,
        entry_acceptable=True,
        requires_public_social_action=False,
    )
    assert decide_status(analysis) == GiveawayStatus.ACTIVE


def test_decide_status_uncertain_unknown_france() -> None:
    from app.extraction.france_eligibility import FranceEligibility

    analysis = GiveawayAnalysis(
        is_giveaway=True,
        confidence=0.9,
        entry_method=EntryMethod.WEB_FORM,
        france_eligibility=FranceEligibility.UNKNOWN,
        wanted_prize=True,
    )
    assert decide_status(analysis) == GiveawayStatus.UNCERTAIN


def test_skip_already_analyzed() -> None:
    from app.config import Settings

    settings = MagicMock(spec=Settings)
    settings.crawl_candidate_threshold = 0.45
    g = _giveaway(analyzed_at=datetime.now(UTC))
    assert should_skip_analysis(g, settings=settings, reanalyze=False) == SkipReason.ALREADY_ANALYZED
    assert should_skip_analysis(g, settings=settings, reanalyze=True) is None


def test_skip_heuristic_rejected() -> None:
    from app.config import Settings

    settings = MagicMock(spec=Settings)
    settings.crawl_candidate_threshold = 0.45
    g = _giveaway(
        title="Windows laptop",
        raw_excerpt="Buy this Windows machine for your office.",
        canonical_url="https://shop.example/products/laptop",
        original_url="https://shop.example/products/laptop",
        domain="shop.example",
    )
    assert should_skip_analysis(g, settings=settings, reanalyze=False) == SkipReason.HEURISTIC_REJECTED


def test_looks_clearly_expired_phrase() -> None:
    g = _giveaway(raw_excerpt="Sorry, this giveaway has ended. Winners have been announced.")
    assert looks_clearly_expired(g) is True


def test_looks_clearly_expired_end_at() -> None:
    g = _giveaway(end_at=datetime.now(UTC) - timedelta(days=1), raw_excerpt="still online archive")
    assert looks_clearly_expired(g) is True


def test_retryable_api_errors() -> None:
    err = genai_errors.APIError(429, {"error": {"message": "rate limited"}})
    assert _is_retryable(err) is True
    bad = genai_errors.APIError(400, {"error": {"message": "invalid argument"}})
    assert _is_retryable(bad) is False


def test_gemini_client_uses_settings_model_and_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import Settings
    from app.gemini.schema import GiveawayBatchAnalysis, GiveawayBatchItemAnalysis

    settings = MagicMock(spec=Settings)
    settings.gemini_api_key = MagicMock()
    settings.gemini_api_key.get_secret_value.return_value = "test-key"
    settings.gemini_model = "models/test-flash"
    settings.gemini_batch_size = 10
    settings.gemini_max_requests_per_minute = 6

    gid = uuid4()
    analysis = GiveawayAnalysis(
        is_giveaway=True,
        title="Test",
        confidence=0.77,
        free_entry=True,
        eligible_france=True,
        entry_method=EntryMethod.WEB_FORM,
        requirements=["email"],
    )
    batch = GiveawayBatchAnalysis(
        items=[
            GiveawayBatchItemAnalysis(
                giveaway_id=gid,
                **analysis.model_dump(),
            )
        ]
    )

    fake_response = MagicMock()
    fake_response.parsed = batch
    fake_response.text = batch.model_dump_json()
    fake_response.usage_metadata = MagicMock(
        prompt_token_count=11,
        candidates_token_count=22,
        total_token_count=33,
    )

    fake_models = MagicMock()
    fake_models.generate_content.return_value = fake_response
    fake_client = MagicMock()
    fake_client.models = fake_models

    monkeypatch.setattr("app.gemini.client.genai.Client", lambda **kwargs: fake_client)

    client = GeminiClient(settings)
    assert client.model == "models/test-flash"
    result = client.analyze_giveaway_page(
        url="https://brand.example/g",
        title="Test",
        text="Participez au jeu concours",
        links=["https://brand.example/reglement"],
        giveaway_id=gid,
    )
    assert isinstance(result, GeminiAnalysisResult)
    assert result.analysis.is_giveaway is True
    assert result.usage == GeminiUsage(11, 22, 33)
    assert fake_models.generate_content.call_args.kwargs["model"] == "models/test-flash"
