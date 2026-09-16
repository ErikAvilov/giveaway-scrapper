"""Service-level analyze batch tests with mocked Gemini client."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from app.content import compute_content_hash
from app.db.connection import connection
from app.db.repository import GiveawayRepository
from app.gemini.client import GeminiBatchResult, GeminiUsage
from app.gemini.schema import EntryMethod, GiveawayBatchItemAnalysis
from app.gemini.service import analyze_giveaways
from app.urls import canonicalize_url


def _batch_item(gid, **kwargs) -> GiveawayBatchItemAnalysis:
    base = {
        "giveaway_id": gid,
        "is_giveaway": True,
        "title": "Concours",
        "summary": "Lot",
        "prize": "Un lot",
        "estimated_prize_value_eur": 100.0,
        "free_entry": True,
        "eligible_france": True,
        "requires_purchase": False,
        "requires_social": False,
        "entry_method": EntryMethod.WEB_FORM,
        "confidence": 0.91,
        "requirements": ["formulaire"],
    }
    base.update(kwargs)
    return GiveawayBatchItemAnalysis(**base)


def test_analyze_batch_persists_mock_result(settings, migrated_db) -> None:
    url = f"https://analyze.test/g/{uuid4()}?utm_source=t"
    canonical = canonicalize_url(url)
    title = "Jeu concours officiel — gagnez"
    excerpt = (
        "Participez à notre jeu concours et remportez un cadeau. "
        "Tirage au sort. Date limite de participation. Règlement du jeu. "
        "Pour participer, remplissez le formulaire. Ouvert aux résidents en France."
    )

    mock_client = MagicMock()
    mock_client.model = "mock-model"
    mock_client.batch_size = 10

    with connection(settings) as conn:
        repo = GiveawayRepository(conn)
        try:
            upserted = repo.upsert_from_crawl(
                url=url,
                title=title,
                raw_excerpt=excerpt,
                link_hints=["https://analyze.test/reglement"],
                content_hash=compute_content_hash(title, None, excerpt),
            )
            conn.commit()
            gid = upserted.giveaway.id
            assert gid is not None

            mock_client.analyze_giveaway_batch.return_value = GeminiBatchResult(
                items=[_batch_item(gid, title=title)],
                usage=GeminiUsage(1, 2, 3),
                model="mock-model",
                raw_text="{}",
            )

            batch = analyze_giveaways(
                conn,
                settings,
                client=mock_client,
                giveaway_id=gid,
            )
            assert batch.analyzed == 1
            assert batch.confirmed == 1
            assert batch.errors == 0
            assert batch.api_requests == 1

            stored = repo.get_by_id(gid)
            assert stored is not None
            assert stored.status.value == "active"
            assert stored.analysis_json is not None
            assert stored.analysis_json["is_giveaway"] is True
            assert stored.eligible_france is True
            mock_client.analyze_giveaway_batch.assert_called_once()
        finally:
            repo.delete_by_canonical_url(canonical)
            conn.commit()


def test_analyze_dry_run_does_not_call_gemini(settings, migrated_db) -> None:
    url = f"https://analyze.test/dry/{uuid4()}"
    canonical = canonicalize_url(url)
    title = "Giveaway sweepstakes enter now"
    excerpt = (
        "Enter now for our sweepstakes. Free entry. Official rules. "
        "Closing date soon. How to enter: fill out the form."
    )
    mock_client = MagicMock()

    with connection(settings) as conn:
        repo = GiveawayRepository(conn)
        try:
            upserted = repo.upsert_from_crawl(
                url=url,
                title=title,
                raw_excerpt=excerpt,
                content_hash=compute_content_hash(title, None, excerpt),
            )
            conn.commit()
            batch = analyze_giveaways(
                conn,
                settings,
                client=mock_client,
                giveaway_id=upserted.giveaway.id,
                dry_run=True,
            )
            assert batch.analyzed == 0
            assert batch.api_requests == 0
            mock_client.analyze_giveaway_batch.assert_not_called()
            stored = repo.get_by_id(upserted.giveaway.id)  # type: ignore[arg-type]
            assert stored is not None
            assert stored.analyzed_at is None
        finally:
            repo.delete_by_canonical_url(canonical)
            conn.commit()
