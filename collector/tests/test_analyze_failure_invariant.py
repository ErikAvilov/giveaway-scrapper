"""Regression: analyzed_at only after successful Gemini persistence."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from google.genai import errors as genai_errors

from app.content import compute_content_hash
from app.db.connection import connection
from app.db.repository import GiveawayRepository
from app.gemini.client import GeminiBatchResult, GeminiUsage
from app.gemini.schema import EntryMethod, GiveawayBatchItemAnalysis
from app.gemini.service import analyze_giveaways
from app.urls import canonicalize_url

_GOOD = (
    "Participez à notre jeu concours et remportez un cadeau. "
    "Tirage au sort. Date limite de participation. Règlement du jeu. "
    "Pour participer, remplissez le formulaire. Ouvert aux résidents en France."
)


def _item(gid, **kwargs) -> GiveawayBatchItemAnalysis:
    data = {
        "giveaway_id": gid,
        "is_giveaway": True,
        "title": "Concours OK",
        "confidence": 0.9,
        "free_entry": True,
        "eligible_france": True,
        "entry_method": EntryMethod.WEB_FORM,
        "requirements": [],
    }
    data.update(kwargs)
    return GiveawayBatchItemAnalysis(**data)


def _seed(conn, token: str, n: int = 1) -> list:
    repo = GiveawayRepository(conn)
    ids = []
    for i in range(n):
        url = f"https://fail-invariant.test/{token}/{i}"
        title = "Jeu concours officiel — gagnez"
        result = repo.upsert_from_crawl(
            url=url,
            title=title,
            raw_excerpt=_GOOD,
            content_hash=compute_content_hash(title, None, _GOOD + str(i)),
        )
        assert result.giveaway.id is not None
        ids.append(result.giveaway.id)
    conn.commit()
    return ids


def _cleanup(conn, token: str, n: int) -> None:
    repo = GiveawayRepository(conn)
    for i in range(n):
        repo.delete_by_canonical_url(canonicalize_url(f"https://fail-invariant.test/{token}/{i}"))
    conn.commit()


def test_http_429_leaves_analyzed_at_null(settings, migrated_db) -> None:
    token = uuid4().hex
    settings.gemini_batch_size = 10
    mock = MagicMock()
    mock.model = "mock"
    mock.batch_size = 10
    mock.analyze_giveaway_batch.side_effect = genai_errors.APIError(
        429,
        {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Please retry in 35s."}},
    )

    with connection(settings) as conn:
        try:
            ids = _seed(conn, token, 1)
            conn.execute(
                "UPDATE giveaways SET manual_status = %s WHERE id = %s",
                ("interested", ids[0]),
            )
            conn.commit()

            batch = analyze_giveaways(
                conn, settings, client=mock, giveaway_ids=ids, limit=1
            )
            assert batch.analyzed == 0
            assert batch.pending == 1
            assert batch.errors == 1

            row = GiveawayRepository(conn).get_by_id(ids[0])
            assert row is not None
            assert row.analyzed_at is None
            assert row.status.value == "candidate"
            assert row.manual_status.value == "interested"
        finally:
            _cleanup(conn, token, 1)


def test_timeout_leaves_analyzed_at_null(settings, migrated_db) -> None:
    token = uuid4().hex
    settings.gemini_batch_size = 10
    mock = MagicMock()
    mock.model = "mock"
    mock.batch_size = 10
    mock.analyze_giveaway_batch.side_effect = TimeoutError("gemini timed out")

    with connection(settings) as conn:
        try:
            ids = _seed(conn, token, 1)
            batch = analyze_giveaways(
                conn, settings, client=mock, giveaway_ids=ids, limit=1
            )
            assert batch.analyzed == 0
            assert batch.pending == 1
            row = GiveawayRepository(conn).get_by_id(ids[0])
            assert row is not None
            assert row.analyzed_at is None
            assert row.status.value == "candidate"
        finally:
            _cleanup(conn, token, 1)


def test_invalid_gemini_response_leaves_analyzed_at_null(settings, migrated_db) -> None:
    token = uuid4().hex
    settings.gemini_batch_size = 10
    mock = MagicMock()
    mock.model = "mock"
    mock.batch_size = 10
    mock.analyze_giveaway_batch.side_effect = ValueError("Gemini returned empty response text")

    with connection(settings) as conn:
        try:
            ids = _seed(conn, token, 1)
            batch = analyze_giveaways(
                conn, settings, client=mock, giveaway_ids=ids, limit=1
            )
            assert batch.analyzed == 0
            assert batch.pending == 1
            row = GiveawayRepository(conn).get_by_id(ids[0])
            assert row is not None
            assert row.analyzed_at is None
            assert row.status.value == "candidate"
        finally:
            _cleanup(conn, token, 1)


def test_successful_response_sets_analyzed_at(settings, migrated_db) -> None:
    token = uuid4().hex
    settings.gemini_batch_size = 10
    mock = MagicMock()
    mock.model = "mock-model"
    mock.batch_size = 10

    with connection(settings) as conn:
        try:
            ids = _seed(conn, token, 1)
            mock.analyze_giveaway_batch.return_value = GeminiBatchResult(
                items=[_item(ids[0])],
                usage=GeminiUsage(),
                model="mock-model",
                raw_text="{}",
            )
            batch = analyze_giveaways(
                conn, settings, client=mock, giveaway_ids=ids, limit=1
            )
            assert batch.analyzed == 1
            row = GiveawayRepository(conn).get_by_id(ids[0])
            assert row is not None
            assert row.analyzed_at is not None
            assert row.status.value == "active"
        finally:
            _cleanup(conn, token, 1)


def test_batch_nine_succeed_one_fails_partial_pending(settings, migrated_db) -> None:
    token = uuid4().hex
    settings.gemini_batch_size = 10
    mock = MagicMock()
    mock.model = "mock"
    mock.batch_size = 10

    with connection(settings) as conn:
        try:
            ids = _seed(conn, token, 10)
            # 9 valid results; one missing → stays pending
            mock.analyze_giveaway_batch.return_value = GeminiBatchResult(
                items=[_item(gid) for gid in ids[:9]],
                usage=GeminiUsage(),
                model="mock",
                raw_text="{}",
            )
            batch = analyze_giveaways(
                conn, settings, client=mock, giveaway_ids=ids, limit=10
            )
            assert batch.analyzed == 9
            assert batch.pending == 1
            assert mock.analyze_giveaway_batch.call_count == 1

            repo = GiveawayRepository(conn)
            analyzed = sum(1 for gid in ids if repo.get_by_id(gid).analyzed_at is not None)  # type: ignore[union-attr]
            pending = sum(
                1
                for gid in ids
                if repo.get_by_id(gid).analyzed_at is None  # type: ignore[union-attr]
                and repo.get_by_id(gid).status.value == "candidate"  # type: ignore[union-attr]
            )
            assert analyzed == 9
            assert pending == 1
        finally:
            _cleanup(conn, token, 10)


def test_api_failure_preserves_manual_status(settings, migrated_db) -> None:
    token = uuid4().hex
    settings.gemini_batch_size = 10
    mock = MagicMock()
    mock.model = "mock"
    mock.batch_size = 10
    mock.analyze_giveaway_batch.side_effect = genai_errors.APIError(
        503, {"error": {"message": "unavailable"}}
    )

    with connection(settings) as conn:
        try:
            ids = _seed(conn, token, 1)
            conn.execute(
                "UPDATE giveaways SET manual_status = %s WHERE id = %s",
                ("entered", ids[0]),
            )
            conn.commit()
            analyze_giveaways(conn, settings, client=mock, giveaway_ids=ids, limit=1)
            row = GiveawayRepository(conn).get_by_id(ids[0])
            assert row is not None
            assert row.analyzed_at is None
            assert row.manual_status.value == "entered"
            assert row.status.value == "candidate"
        finally:
            _cleanup(conn, token, 1)
