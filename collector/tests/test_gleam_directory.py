"""Tests for Gleam directory discovery (/giveaways + /giveaways/<id>)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from scrapling.parser import Selector

from app.config import Settings
from app.db.connection import connection
from app.db.repository import GiveawayRepository
from app.extraction.entry_acceptability import assess_entry_acceptability
from app.gemini.service import SkipReason, should_skip_analysis
from app.models.giveaway import Giveaway, GiveawayStatus, ManualStatus
from app.platforms.gleam import (
    canonicalize_gleam_directory_list_url,
    extract_campaign_widget_url,
    gleam_identity_from_url,
    is_gleam_directory_listing,
    parse_gleam_campaign_url,
    parse_gleam_directory_detail_url,
)
from app.platforms.gleam_directory import (
    extract_directory_cards,
    extract_directory_pagination_urls,
)
from app.scraping.adapters.gleam import GleamAdapter
from app.urls import canonicalize_url

FIXTURES = Path(__file__).parent / "fixtures" / "html"


def _html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def db_conn(settings, migrated_db):
    with connection(settings) as conn:
        yield conn


def test_url_patterns_listing_detail_classic() -> None:
    assert is_gleam_directory_listing("https://gleam.io/giveaways")
    assert is_gleam_directory_listing("https://gleam.io/giveaways?s=n&p=2")
    assert not is_gleam_directory_listing("https://gleam.io/giveaways/gB6Mc")

    assert parse_gleam_directory_detail_url("https://gleam.io/giveaways/gB6Mc") == "gB6Mc"
    assert parse_gleam_directory_detail_url("https://gleam.io/giveaways") is None
    assert parse_gleam_directory_detail_url("https://gleam.io/giveaways/by") is None

    key, slug = parse_gleam_campaign_url("https://gleam.io/74PCt/win-a-jacket")
    assert key == "74PCt"
    assert slug and slug.startswith("win-a")
    assert parse_gleam_campaign_url("https://gleam.io/giveaways/gB6Mc") == (None, None)


def test_directory_listing_extracts_cards_not_marketing() -> None:
    html = _html("gleam_directory.html")
    cards = extract_directory_cards(html)
    ids = {c.directory_id for c in cards}
    assert "gB6Mc" in ids
    assert "ln0Zn" in ids
    assert "3tR8E" in ids
    assert "Ab12Cd" in ids
    assert "by" not in ids
    titles = [c.title for c in cards]
    assert any(t and "PlayStation" in t for t in titles)
    assert any(c.priority_prize_hint for c in cards)

    follow_blob = " ".join(c.detail_url for c in cards)
    for bad in ("/guides", "/pricing", "/blog", "/terms", "/templates", "/login"):
        assert bad not in follow_blob


def test_directory_pagination_bounded_skips_ended() -> None:
    html = _html("gleam_directory.html")
    pages = extract_directory_pagination_urls(html, max_pages=5)
    assert any(p.endswith("/giveaways") or "?s=n" in p for p in pages)
    assert all("s=f" not in p for p in pages)
    assert canonicalize_gleam_directory_list_url("https://gleam.io/giveaways?s=f") is None
    assert (
        canonicalize_gleam_directory_list_url(
            "https://gleam.io/giveaways?g=336&m=321&p=2"
        )
        == "https://gleam.io/giveaways?p=2"
    )
    assert len(pages) <= 5


def test_adapter_listing_whitelists_follow_urls() -> None:
    adapter = GleamAdapter()
    listing = adapter.enrich(
        Selector(_html("gleam_directory.html")),
        page_url="https://gleam.io/giveaways",
    )
    assert listing.skip_as_candidate is True
    assert listing.follow_urls
    # Listing schedules classic /<id>/x pages (parse targets), not shell /giveaways/<id>.
    assert any(re.search(r"gleam\.io/gB6Mc/", u) for u in listing.follow_urls)
    assert all("/pricing" not in u for u in listing.follow_urls)
    assert all("/guides" not in u for u in listing.follow_urls)
    assert listing.meta.get("giveaway_links_discovered", 0) >= 4
    assert listing.meta.get("sample_detail_urls")
    assert any("/giveaways/gB6Mc" in u for u in listing.meta["sample_detail_urls"])


def test_adapter_directory_detail_follows_classic_widget() -> None:
    adapter = GleamAdapter()
    detail = adapter.enrich(
        Selector(_html("gleam_directory_detail.html")),
        page_url="https://gleam.io/giveaways/gB6Mc",
    )
    assert detail.skip_as_candidate is True
    assert detail.follow_urls
    assert detail.follow_urls[0].startswith("https://gleam.io/gB6Mc/")
    assert detail.meta.get("platform_campaign_id") == "gB6Mc"
    assert extract_campaign_widget_url(_html("gleam_directory_detail.html"))


def test_directory_and_classic_share_campaign_identity() -> None:
    d = gleam_identity_from_url("https://gleam.io/giveaways/gB6Mc")
    c = gleam_identity_from_url("https://gleam.io/gB6Mc/playstation-pro")
    assert d is not None and c is not None
    assert d["platform_campaign_id"] == c["platform_campaign_id"] == "gB6Mc"


def test_mandatory_public_social_rejects_optional_does_not() -> None:
    bad = assess_entry_acceptability(
        platform_actions=[
            {"entry_type": "email_subscribe", "mandatory": True},
            {"entry_type": "instagram_comment", "mandatory": True},
        ]
    )
    assert bad.entry_acceptable is False

    ok = assess_entry_acceptability(
        body="Follow us on Instagram",
        platform_actions=[
            {"entry_type": "email_subscribe", "mandatory": True},
            {"entry_type": "instagram_comment", "mandatory": False},
            {"entry_type": "twitter_retweet", "mandatory": False},
        ],
    )
    assert ok.entry_acceptable is True
    assert ok.has_non_public_entry_path is True


def test_upsert_dedup_same_campaign_key(db_conn, settings) -> None:
    del settings
    repo = GiveawayRepository(db_conn)
    token = f"d{uuid4().hex[:7]}"
    url_dir = f"https://gleam.io/giveaways/{token}"
    url_classic = f"https://gleam.io/{token}/playstation-pro-grand-theft-auto"
    try:
        a = repo.upsert_from_crawl(
            url=url_dir,
            title="PlayStation Pro + Grand Theft Auto",
            content_hash="h1",
            platform="gleam",
            platform_campaign_id=token,
            entry_url=url_classic,
            wanted_prize=True,
            entry_acceptable=True,
            eligible_france=True,
        )
        assert a.giveaway.id is not None
        repo.save_analysis(
            a.giveaway.id,
            analysis_json={"ok": True},
            status=GiveawayStatus.ACTIVE,
            confidence=0.9,
            wanted_prize=True,
            entry_acceptable=True,
            eligible_france=True,
            france_eligibility="eligible",
        )
        b = repo.upsert_from_crawl(
            url=url_classic,
            title="PlayStation Pro + Grand Theft Auto",
            content_hash="h2",
            platform="gleam",
            platform_campaign_id=token,
            entry_url=url_classic,
        )
        assert a.created is True
        assert b.created is False
        assert a.giveaway.id == b.giveaway.id
        assert b.giveaway.analyzed_at is not None
        assert b.giveaway.manual_status == ManualStatus.NONE
    finally:
        repo.delete_by_canonical_url(canonicalize_url(url_dir))
        repo.delete_by_canonical_url(canonicalize_url(url_classic))


def test_entered_not_requeued_for_ai() -> None:
    settings = MagicMock(spec=Settings)
    settings.crawl_candidate_threshold = 0.45
    g = Giveaway(
        id=uuid4(),
        canonical_url="https://gleam.io/gB6Mc/ps5",
        original_url="https://gleam.io/gB6Mc/ps5",
        domain="gleam.io",
        title="PlayStation giveaway",
        content_hash="abc",
        raw_excerpt="Participez au jeu concours PS5. Tirage au sort. Règlement.",
        status=GiveawayStatus.ACTIVE,
        analyzed_at=None,
        manual_status=ManualStatus.ENTERED,
        platform="gleam",
        platform_campaign_id="gB6Mc",
    )
    assert (
        should_skip_analysis(g, settings=settings, reanalyze=False)
        == SkipReason.TERMINAL_MANUAL
    )


def test_analyzed_not_resent() -> None:
    settings = MagicMock(spec=Settings)
    settings.crawl_candidate_threshold = 0.45
    g = Giveaway(
        id=uuid4(),
        canonical_url="https://gleam.io/gB6Mc/ps5",
        original_url="https://gleam.io/gB6Mc/ps5",
        domain="gleam.io",
        title="PlayStation giveaway",
        content_hash="abc",
        raw_excerpt="Participez au jeu concours PS5. Tirage au sort. Règlement.",
        status=GiveawayStatus.ACTIVE,
        analyzed_at=datetime.now(UTC),
        manual_status=ManualStatus.NONE,
    )
    assert (
        should_skip_analysis(g, settings=settings, reanalyze=False)
        == SkipReason.ALREADY_ANALYZED
    )


def test_classic_campaign_fixture_still_parses() -> None:
    adapter = GleamAdapter()
    easy = adapter.enrich(
        Selector(_html("gleam_easy.html")),
        page_url="https://gleam.io/74PCt/win-a-jacket",
    )
    assert easy.skip_as_candidate is False
    assert easy.meta.get("platform") == "gleam"
    assert easy.meta.get("platform_campaign_id")
    assert easy.meta.get("parse_status") == "ok"


def test_diagnose_parse_failure_reasons() -> None:
    from app.platforms.gleam import diagnose_gleam_parse_failure

    assert (
        diagnose_gleam_parse_failure("", page_url="https://gleam.io/gB6Mc/x", http_status=404)
        == "HTTP status 404"
    )
    assert (
        diagnose_gleam_parse_failure(
            "<html></html>", page_url="https://gleam.io/giveaways/gB6Mc"
        )
        == "unsupported directory detail shape"
    )
    assert (
        diagnose_gleam_parse_failure("<html>no payload</html>", page_url="https://gleam.io/gB6Mc/x")
        == "no initCampaign payload"
    )
    assert (
        diagnose_gleam_parse_failure(
            '<meta http-equiv="refresh" content="0;url=/">',
            page_url="https://gleam.io/gB6Mc/x",
        )
        == "redirect"
    )