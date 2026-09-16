"""Regression: pipeline --limit must be a hard Gemini call cap."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.content import compute_content_hash
from app.db.connection import connection
from app.db.repository import GiveawayRepository
from app.gemini.client import GeminiUsage
from app.gemini.schema import EntryMethod, GiveawayAnalysis
from app.gemini.service import analyze_giveaways
from app.models.crawl_run import CrawlRunStatus
from app.pipeline import run_pipeline
from app.scraping.runner import SourceCrawlResult
from app.urls import canonicalize_url


def _mock_analysis() -> GiveawayAnalysis:
    return GiveawayAnalysis(
        is_giveaway=True,
        title="Concours",
        summary="Lot",
        prize="Cadeau",
        free_entry=True,
        eligible_france=True,
        requires_purchase=False,
        requires_social=False,
        entry_method=EntryMethod.WEB_FORM,
        confidence=0.9,
        requirements=[],
    )


def test_pipeline_passes_hard_analyze_limit_even_when_needs_analysis_is_huge(
    settings,
) -> None:
    """Former bug: limit was inflated to max(limit, needs_analysis)."""
    crawl_results = [
        SourceCrawlResult(
            source_id=uuid4(),
            source_name="huge",
            pages_fetched=10,
            candidates_found=500,
            giveaways_created=500,
            giveaways_updated=0,
            previously_known=0,
            needs_analysis=500,
            errors_count=0,
            status=CrawlRunStatus.SUCCESS,
            error_summary=None,
            candidates=[],
        )
    ]
    analyze_result = MagicMock()
    analyze_result.analyzed = 25
    analyze_result.confirmed = 0
    analyze_result.rejected = 0
    analyze_result.uncertain = 0
    analyze_result.expired = 0
    analyze_result.errors = 0

    with (
        patch("app.pipeline.crawl_all", return_value=crawl_results) as crawl_mock,
        patch("app.pipeline.analyze_giveaways", return_value=analyze_result) as analyze_mock,
    ):
        summary = run_pipeline(
            MagicMock(),
            settings,
            analyze_limit=25,
            dry_run=False,
        )

    crawl_mock.assert_called_once()
    analyze_mock.assert_called_once()
    assert analyze_mock.call_args.kwargs["limit"] == 25
    assert summary.gemini_analyses == 25


def test_five_hundred_pending_with_limit_25_never_exceeds_25_gemini_calls(
    settings, migrated_db
) -> None:
    from app.gemini.client import GeminiBatchResult
    from app.gemini.schema import GiveawayBatchItemAnalysis

    token = uuid4().hex
    urls: list[str] = []
    ids = []
    title = "Jeu concours officiel — gagnez un lot"
    excerpt = (
        "Participez à notre jeu concours et remportez un cadeau. "
        "Tirage au sort. Date limite de participation. Règlement du jeu. "
        "Pour participer, remplissez le formulaire. Ouvert aux résidents en France."
    )
    analysis = _mock_analysis()
    mock_client = MagicMock()
    mock_client.model = "mock-model"
    mock_client.batch_size = 10

    def _batch_side_effect(items):
        return GeminiBatchResult(
            items=[
                GiveawayBatchItemAnalysis(
                    giveaway_id=item.giveaway_id,
                    **analysis.model_dump(),
                )
                for item in items
            ],
            usage=GeminiUsage(1, 1, 2),
            model="mock-model",
            raw_text="{}",
        )

    mock_client.analyze_giveaway_batch.side_effect = _batch_side_effect

    with connection(settings) as conn:
        repo = GiveawayRepository(conn)
        try:
            for i in range(500):
                url = f"https://limit-cap.test/{token}/{i}"
                urls.append(url)
                result = repo.upsert_from_crawl(
                    url=url,
                    title=title,
                    raw_excerpt=excerpt,
                    content_hash=compute_content_hash(title, None, excerpt + str(i)),
                )
                assert result.giveaway.id is not None
                ids.append(result.giveaway.id)
            conn.commit()

            batch = analyze_giveaways(
                conn,
                settings,
                client=mock_client,
                limit=25,
                giveaway_ids=ids[:25],
            )
            # 25 giveaways / batch_size 10 => at most 3 API requests
            assert mock_client.analyze_giveaway_batch.call_count <= 3
            assert batch.analyzed <= 25
            assert batch.processed <= 25

            still_pending = repo.list_needing_analysis(limit=1000)
            pending_ours = [
                g for g in still_pending if f"/{token}/" in str(g.canonical_url)
            ]
            assert len(pending_ours) >= 500 - 25
        finally:
            for url in urls:
                repo.delete_by_canonical_url(canonicalize_url(url))
            conn.commit()
