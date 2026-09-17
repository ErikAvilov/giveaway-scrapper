"""Tests for analyze --all draining the pending Gemini queue."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from click.testing import CliRunner

from app.cli import main
from app.content import compute_content_hash
from app.db.connection import connection
from app.db.repository import GiveawayRepository
from app.gemini.client import GeminiBatchResult, GeminiUsage
from app.gemini.rate_limit import RequestRateLimiter
from app.gemini.schema import EntryMethod, GiveawayBatchItemAnalysis
from app.gemini.service import analyze_all_pending, analyze_giveaways
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
        url = f"https://analyze-all.test/{token}/{i}"
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
        repo.delete_by_canonical_url(
            canonicalize_url(f"https://analyze-all.test/{token}/{i}")
        )
    conn.commit()


def _mock_client() -> MagicMock:
    mock = MagicMock()
    mock.model = "mock"
    mock.batch_size = 10
    mock._rate_limiter = RequestRateLimiter(6)
    mock.analyze_giveaway_batch.side_effect = lambda items: GeminiBatchResult(
        items=[_item(i.giveaway_id) for i in items],
        usage=GeminiUsage(),
        model="mock",
        raw_text="{}",
    )
    return mock


def test_analyze_all_130_pending_batch_10_makes_13_api_requests(settings, migrated_db) -> None:
    token = uuid4().hex
    settings.gemini_batch_size = 10
    mock = _mock_client()
    limiter_id = id(mock._rate_limiter)

    with connection(settings) as conn:
        try:
            ids = _seed_pending(conn, 130, token)
            assert GiveawayRepository(conn).count_pending_analysis(only_ids=ids) == 130

            result = analyze_all_pending(conn, settings, client=mock, only_ids=ids)
            assert result.pending_at_start == 130
            assert result.batch_count == 13
            assert result.result.api_requests == 13
            assert result.result.analyzed == 130
            assert mock.analyze_giveaway_batch.call_count == 13
            sizes = [len(c.args[0]) for c in mock.analyze_giveaway_batch.call_args_list]
            assert sizes == [10] * 13
            assert GiveawayRepository(conn).count_pending_analysis(only_ids=ids) == 0
            # Same limiter instance for the whole run.
            assert id(mock._rate_limiter) == limiter_id
        finally:
            _cleanup(conn, token, 130)


def test_analyze_all_continues_until_queue_empty(settings, migrated_db) -> None:
    token = uuid4().hex
    settings.gemini_batch_size = 10
    mock = _mock_client()
    progress: list[dict] = []

    with connection(settings) as conn:
        try:
            ids = _seed_pending(conn, 25, token)
            result = analyze_all_pending(
                conn,
                settings,
                client=mock,
                only_ids=ids,
                on_progress=progress.append,
            )
            assert result.result.analyzed == 25
            assert result.batch_count == 3
            assert progress[0] == {"event": "start", "pending": 25}
            assert progress[-1] == {"event": "done"}
            batch_events = [e for e in progress if e.get("event") == "batch"]
            assert batch_events[-1]["remaining"] == 0
            assert GiveawayRepository(conn).count_pending_analysis(only_ids=ids) == 0
        finally:
            _cleanup(conn, token, 25)


def test_analyze_limit_20_still_stops_after_20(settings, migrated_db) -> None:
    token = uuid4().hex
    settings.gemini_batch_size = 10
    mock = _mock_client()

    with connection(settings) as conn:
        try:
            ids = _seed_pending(conn, 50, token)
            batch = analyze_giveaways(
                conn, settings, client=mock, limit=20, giveaway_ids=ids
            )
            assert batch.analyzed == 20
            assert mock.analyze_giveaway_batch.call_count == 2
            assert GiveawayRepository(conn).count_pending_analysis(only_ids=ids) == 30
        finally:
            _cleanup(conn, token, 50)


def test_analyze_all_failed_items_do_not_infinite_loop(settings, migrated_db) -> None:
    token = uuid4().hex
    settings.gemini_batch_size = 10
    mock = MagicMock()
    mock.model = "mock"
    mock.batch_size = 10
    mock._rate_limiter = RequestRateLimiter(6)
    # Every API call fails — each chunk is excluded; loop must terminate.
    mock.analyze_giveaway_batch.side_effect = TimeoutError("gemini down")

    with connection(settings) as conn:
        try:
            ids = _seed_pending(conn, 25, token)
            result = analyze_all_pending(conn, settings, client=mock, only_ids=ids)
            assert result.batch_count == 3
            assert mock.analyze_giveaway_batch.call_count == 3
            assert result.result.analyzed == 0
            assert result.result.errors == 25
            # Failures remain pending in DB.
            assert GiveawayRepository(conn).count_pending_analysis(only_ids=ids) == 25
        finally:
            _cleanup(conn, token, 25)


def test_analyze_all_reuses_same_rate_limiter_instance(settings, migrated_db) -> None:
    token = uuid4().hex
    settings.gemini_batch_size = 5
    mock = _mock_client()
    seen_limiters: list[int] = []

    original = mock.analyze_giveaway_batch.side_effect

    def _track(items):
        seen_limiters.append(id(mock._rate_limiter))
        return original(items)

    mock.analyze_giveaway_batch.side_effect = _track

    with connection(settings) as conn:
        try:
            ids = _seed_pending(conn, 15, token)
            analyze_all_pending(conn, settings, client=mock, only_ids=ids)
            assert len(seen_limiters) == 3
            assert len(set(seen_limiters)) == 1
        finally:
            _cleanup(conn, token, 15)


def test_cli_all_and_limit_are_mutually_exclusive() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["analyze", "--all", "--limit", "20"])
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower() or "mutually exclusive" in (
        result.exception.args[0].lower() if result.exception else ""
    )
