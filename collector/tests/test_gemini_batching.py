"""Regression tests for Gemini micro-batching, mapping, 429, and RPM throttle."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from google.genai import errors as genai_errors
from google.genai import types

from app.content import compute_content_hash
from app.db.connection import connection
from app.db.repository import GiveawayRepository
from app.gemini.client import (
    GeminiBatchResult,
    GeminiClient,
    GeminiUsage,
    GiveawayPageInput,
    _is_retryable,
    quota_retry_delay_seconds,
)
from app.gemini.rate_limit import RequestRateLimiter
from app.gemini.schema import EntryMethod, GiveawayBatchAnalysis, GiveawayBatchItemAnalysis
from app.gemini.service import analyze_giveaways, map_batch_items_by_id
from app.urls import canonicalize_url

_GOOD_EXCERPT = (
    "Participez à notre jeu concours et remportez un cadeau. "
    "Tirage au sort. Date limite de participation. Règlement du jeu. "
    "Pour participer, remplissez le formulaire. Ouvert aux résidents en France."
)


def _item(gid, **kwargs) -> GiveawayBatchItemAnalysis:
    data = {
        "giveaway_id": gid,
        "is_giveaway": True,
        "title": "Concours",
        "confidence": 0.9,
        "free_entry": True,
        "eligible_france": True,
        "entry_method": EntryMethod.WEB_FORM,
        "requirements": [],
    }
    data.update(kwargs)
    return GiveawayBatchItemAnalysis(**data)


def _seed_pending(conn, n: int, token: str) -> list:
    repo = GiveawayRepository(conn)
    ids = []
    for i in range(n):
        url = f"https://batch.test/{token}/{i}"
        title = "Jeu concours officiel — gagnez"
        result = repo.upsert_from_crawl(
            url=url,
            title=title,
            raw_excerpt=_GOOD_EXCERPT,
            content_hash=compute_content_hash(title, None, _GOOD_EXCERPT + str(i)),
        )
        assert result.giveaway.id is not None
        ids.append(result.giveaway.id)
    conn.commit()
    return ids


def _cleanup(conn, token: str, n: int) -> None:
    repo = GiveawayRepository(conn)
    for i in range(n):
        repo.delete_by_canonical_url(canonicalize_url(f"https://batch.test/{token}/{i}"))
    conn.commit()


def test_limit_25_batch_10_makes_at_most_3_api_requests(settings, migrated_db) -> None:
    token = uuid4().hex
    settings.gemini_batch_size = 10
    mock = MagicMock()
    mock.model = "mock"
    mock.batch_size = 10

    def _side_effect(items):
        return GeminiBatchResult(
            items=[_item(i.giveaway_id) for i in items],
            usage=GeminiUsage(),
            model="mock",
            raw_text="{}",
        )

    mock.analyze_giveaway_batch.side_effect = _side_effect

    with connection(settings) as conn:
        try:
            ids = _seed_pending(conn, 25, token)
            batch = analyze_giveaways(
                conn, settings, client=mock, limit=25, giveaway_ids=ids
            )
            assert batch.api_requests == 3
            assert batch.analyzed == 25
            assert mock.analyze_giveaway_batch.call_count == 3
            sizes = [len(c.args[0]) for c in mock.analyze_giveaway_batch.call_args_list]
            assert sizes == [10, 10, 5]
        finally:
            _cleanup(conn, token, 25)


def test_limit_100_batch_10_makes_at_most_10_api_requests(settings, migrated_db) -> None:
    token = uuid4().hex
    settings.gemini_batch_size = 10
    mock = MagicMock()
    mock.model = "mock"
    mock.batch_size = 10
    mock.analyze_giveaway_batch.side_effect = lambda items: GeminiBatchResult(
        items=[_item(i.giveaway_id) for i in items],
        usage=GeminiUsage(),
        model="mock",
        raw_text="{}",
    )

    with connection(settings) as conn:
        try:
            ids = _seed_pending(conn, 100, token)
            batch = analyze_giveaways(
                conn, settings, client=mock, limit=100, giveaway_ids=ids
            )
            assert batch.api_requests == 10
            assert batch.analyzed == 100
            assert mock.analyze_giveaway_batch.call_count == 10
        finally:
            _cleanup(conn, token, 100)


def test_limit_7_single_request_max_7_items(settings, migrated_db) -> None:
    token = uuid4().hex
    settings.gemini_batch_size = 10
    mock = MagicMock()
    mock.model = "mock"
    mock.batch_size = 10
    mock.analyze_giveaway_batch.side_effect = lambda items: GeminiBatchResult(
        items=[_item(i.giveaway_id) for i in items],
        usage=GeminiUsage(),
        model="mock",
        raw_text="{}",
    )

    with connection(settings) as conn:
        try:
            ids = _seed_pending(conn, 7, token)
            batch = analyze_giveaways(
                conn, settings, client=mock, limit=7, giveaway_ids=ids
            )
            assert batch.api_requests == 1
            assert len(mock.analyze_giveaway_batch.call_args.args[0]) == 7
            assert batch.analyzed == 7
        finally:
            _cleanup(conn, token, 7)


def test_results_map_by_giveaway_id_not_array_position(settings, migrated_db) -> None:
    token = uuid4().hex
    settings.gemini_batch_size = 10
    mock = MagicMock()
    mock.model = "mock"
    mock.batch_size = 10

    with connection(settings) as conn:
        try:
            ids = _seed_pending(conn, 3, token)
            # Return items in reverse order with distinct titles keyed by id.
            mock.analyze_giveaway_batch.return_value = GeminiBatchResult(
                items=[
                    _item(ids[2], title="Third"),
                    _item(ids[0], title="First"),
                    _item(ids[1], title="Second"),
                ],
                usage=GeminiUsage(),
                model="mock",
                raw_text="{}",
            )
            batch = analyze_giveaways(
                conn, settings, client=mock, limit=3, giveaway_ids=ids
            )
            assert batch.analyzed == 3
            repo = GiveawayRepository(conn)
            assert repo.get_by_id(ids[0]).title == "First"  # type: ignore[union-attr]
            assert repo.get_by_id(ids[1]).title == "Second"  # type: ignore[union-attr]
            assert repo.get_by_id(ids[2]).title == "Third"  # type: ignore[union-attr]
        finally:
            _cleanup(conn, token, 3)


def test_missing_response_item_stays_pending(settings, migrated_db) -> None:
    token = uuid4().hex
    settings.gemini_batch_size = 10
    mock = MagicMock()
    mock.model = "mock"
    mock.batch_size = 10

    with connection(settings) as conn:
        try:
            ids = _seed_pending(conn, 3, token)
            mock.analyze_giveaway_batch.return_value = GeminiBatchResult(
                items=[_item(ids[0]), _item(ids[2])],  # missing ids[1]
                usage=GeminiUsage(),
                model="mock",
                raw_text="{}",
            )
            batch = analyze_giveaways(
                conn, settings, client=mock, limit=3, giveaway_ids=ids
            )
            assert batch.analyzed == 2
            assert batch.pending == 1
            assert mock.analyze_giveaway_batch.call_count == 1  # no immediate resend
            repo = GiveawayRepository(conn)
            missing = repo.get_by_id(ids[1])
            assert missing is not None
            assert missing.analyzed_at is None
            assert missing.status.value == "candidate"
        finally:
            _cleanup(conn, token, 3)


def test_duplicate_and_unknown_ids_rejected_safely() -> None:
    a, b, unknown = uuid4(), uuid4(), uuid4()
    valid, missing, messages = map_batch_items_by_id(
        expected_ids={a, b},
        items=[
            _item(a, title="ok"),
            _item(unknown, title="nope"),
            _item(a, title="dup"),
            _item(b, title="bee"),
        ],
    )
    assert b in valid
    assert a not in valid  # duplicate discarded
    assert missing == {a}
    assert any("unknown" in m for m in messages)
    assert any("duplicate" in m for m in messages)


def test_quota_retry_honors_retryinfo_seconds() -> None:
    err = genai_errors.APIError(
        429,
        {
            "error": {
                "status": "RESOURCE_EXHAUSTED",
                "message": "Please retry in 35s.",
                "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "35s"}],
            }
        },
    )
    assert _is_retryable(err) is True
    delay = quota_retry_delay_seconds(err)
    assert delay >= 36.0  # 35 + 1s margin
    assert delay < 40.0


def test_quota_retry_fallback_when_unparseable() -> None:
    err = genai_errors.APIError(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "busy"}})
    delay = quota_retry_delay_seconds(err)
    assert delay == 61.0


def test_rate_limiter_throttles_with_mocked_clock() -> None:
    clock = {"t": 1000.0}
    sleeps: list[float] = []

    def now() -> float:
        return clock["t"]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["t"] += seconds

    limiter = RequestRateLimiter(2, clock=now, sleeper=sleep)
    limiter.acquire()  # t=1000
    limiter.acquire()  # t=1000
    limiter.acquire()  # must wait ~60s
    assert sleeps
    assert sleeps[0] >= 59.0
    assert clock["t"] >= 1059.0


def test_gemini_client_batch_uses_schema_and_disables_afc(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import Settings

    settings = MagicMock(spec=Settings)
    settings.gemini_api_key = MagicMock()
    settings.gemini_api_key.get_secret_value.return_value = "test-key"
    settings.gemini_model = "gemini-3.5-flash-lite"
    settings.gemini_batch_size = 10
    settings.gemini_max_requests_per_minute = 6

    gid = uuid4()
    batch = GiveawayBatchAnalysis(items=[_item(gid)])
    fake_response = MagicMock()
    fake_response.parsed = batch
    fake_response.text = batch.model_dump_json()
    fake_response.usage_metadata = MagicMock(
        prompt_token_count=1, candidates_token_count=2, total_token_count=3
    )
    fake_models = MagicMock()
    fake_models.generate_content.return_value = fake_response
    fake_client = MagicMock()
    fake_client.models = fake_models
    monkeypatch.setattr("app.gemini.client.genai.Client", lambda **kwargs: fake_client)

    client = GeminiClient(settings, rate_limiter=RequestRateLimiter(100))
    result = client.analyze_giveaway_batch(
        [GiveawayPageInput(giveaway_id=gid, url="https://x", title="t", text="jeu concours", links=[])]
    )
    assert len(result.items) == 1
    assert result.items[0].giveaway_id == gid
    kwargs = fake_models.generate_content.call_args.kwargs
    assert kwargs["model"] == "gemini-3.5-flash-lite"
    config = kwargs["config"]
    assert isinstance(config, types.GenerateContentConfig)
    assert config.response_schema is GiveawayBatchAnalysis
    assert config.automatic_function_calling is not None
    assert config.automatic_function_calling.disable is True


def test_429_retry_sleeps_server_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import Settings

    settings = MagicMock(spec=Settings)
    settings.gemini_api_key = MagicMock()
    settings.gemini_api_key.get_secret_value.return_value = "test-key"
    settings.gemini_model = "gemini-3.5-flash-lite"
    settings.gemini_batch_size = 10
    settings.gemini_max_requests_per_minute = 100

    err = genai_errors.APIError(429, {"error": {"message": "Please retry in 35s."}})
    gid = uuid4()
    ok = GiveawayBatchAnalysis(items=[_item(gid)])
    fake_response = MagicMock()
    fake_response.parsed = ok
    fake_response.text = ok.model_dump_json()
    fake_response.usage_metadata = None

    fake_models = MagicMock()
    fake_models.generate_content.side_effect = [err, fake_response]
    fake_client = MagicMock()
    fake_client.models = fake_models
    monkeypatch.setattr("app.gemini.client.genai.Client", lambda **kwargs: fake_client)

    sleeps: list[float] = []
    monkeypatch.setattr("app.gemini.client.time.sleep", lambda s: sleeps.append(s))

    client = GeminiClient(settings, rate_limiter=RequestRateLimiter(100))
    result = client.analyze_giveaway_batch(
        [GiveawayPageInput(giveaway_id=gid, url="https://x", title="t", text="concours", links=[])]
    )
    assert result.items[0].giveaway_id == gid
    assert sleeps
    assert sleeps[0] >= 36.0
