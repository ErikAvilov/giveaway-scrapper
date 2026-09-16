"""Tests for international adapters, geo/friction assessment, and filters."""

from __future__ import annotations

from pathlib import Path

from scrapling.parser import Selector

from app.extraction.entry_assessment import (
    EntryFriction,
    GeoScope,
    assess_entry,
    classify_entry_friction,
    detect_undesirable,
    infer_eligible_france,
    infer_geo_scope,
)
from app.scraping.adapters.contestgirl import ContestGirlAdapter, decode_contestgirl_url
from app.scraping.adapters.giveario import GivearioAdapter
from app.scraping.adapters.online_competition import OnlineCompetitionAdapter
from app.scraping.adapters.prize_runner import PrizeRunnerAdapter
from app.scraping.adapters.the_prize_finder import ThePrizeFinderAdapter
from app.scraping.diagnostics import build_candidate_diagnostics

FIXTURES = Path(__file__).parent / "fixtures" / "html"


def _selector(name: str) -> Selector:
    return Selector((FIXTURES / name).read_text(encoding="utf-8"))


class _RssResponse:
    """Minimal response stand-in exposing raw RSS bytes for the adapter."""

    def __init__(self, data: bytes) -> None:
        self.body = data

    def css(self, _selector: str):
        return []


def test_geo_worldwide_eligible_france() -> None:
    assert infer_geo_scope("Worldwide") == GeoScope.WORLDWIDE
    assert infer_eligible_france(restriction="Worldwide") is True


def test_geo_uk_only_not_france() -> None:
    text = "UK Residents only - aged 18 or over"
    assert infer_geo_scope(text) == GeoScope.UK
    assert infer_eligible_france(restriction=text) is False


def test_geo_us_only_not_france() -> None:
    text = "US Residents only"
    assert infer_geo_scope(text) == GeoScope.US
    assert infer_eligible_france(restriction=text) is False


def test_geo_ambiguous_null() -> None:
    assert infer_eligible_france(restriction=None) is None
    assert infer_eligible_france(restriction="See official rules") is None


def test_entry_friction_easy_medium_hard() -> None:
    easy, method = classify_entry_friction(instructions="Enter your details")
    assert easy == EntryFriction.EASY
    assert method == "web_form"

    medium, _ = classify_entry_friction(instructions="Create an account then enter")
    assert medium == EntryFriction.MEDIUM

    hard, _ = classify_entry_friction(instructions="Purchase required to enter. Buy to enter.")
    assert hard == EntryFriction.HARD


def test_purchase_paid_postal_detection() -> None:
    assert "purchase_required" in detect_undesirable(body="Purchase required to win")
    assert "paid_entry" in detect_undesirable(body="Paid entry ticket to enter")
    assert "postal_only" in detect_undesirable(body="Postal entries only via SAE")


def test_assess_skips_gemini_for_casino() -> None:
    a = assess_entry(title="Get up to 500 Free Spins - No Deposit Needed", body="casino offer")
    assert a.skip_gemini is True
    assert "casino" in a.skip_reasons


def test_giveario_listing_and_detail() -> None:
    adapter = GivearioAdapter()
    listing = adapter.enrich(
        _selector("giveario_listing.html"),
        page_url="https://giveario.com/en/countries/united-states/",
    )
    assert listing.skip_as_candidate is True
    assert listing.follow_urls
    assert any("oreo-flavor" in u for u in listing.follow_urls)

    detail = adapter.enrich(
        _selector("giveario_detail.html"),
        page_url="https://giveario.com/en/giveaways/oreo-flavor-vote-sweepstakes-2026/",
    )
    assert detail.skip_as_candidate is False
    assert detail.entry_url == "https://www.oreo.com/twist-lick-vote"
    assert detail.terms_url is not None
    assert detail.restriction_text == "United States"
    assert detail.prize is not None
    assessment = assess_entry(
        title=detail.title,
        body=detail.excerpt,
        instructions=detail.entry_method_text,
        restriction=detail.restriction_text,
        purchase_required_text=(detail.meta or {}).get("purchase_required_text"),
    )
    assert assessment.eligible_france is False
    assert assessment.free_entry is True


def test_giveario_worldwide_eligibility() -> None:
    adapter = GivearioAdapter()
    detail = adapter.enrich(
        _selector("giveario_detail_worldwide.html"),
        page_url="https://giveario.com/en/giveaways/global-gadget-giveaway/",
    )
    assert detail.restriction_text == "Worldwide"
    a = assess_entry(
        title=detail.title,
        body=detail.excerpt,
        instructions=detail.entry_method_text,
        restriction=detail.restriction_text,
        purchase_required_text="No",
        free_hint=True,
    )
    assert a.eligible_france is True
    assert a.entry_friction == EntryFriction.EASY


def test_the_prize_finder_rss_and_detail() -> None:
    adapter = ThePrizeFinderAdapter()
    raw = (FIXTURES / "the_prize_finder_rss.xml").read_bytes()
    hub = adapter.enrich(
        _RssResponse(raw),
        page_url="https://www.theprizefinder.com/rss.xml",
    )
    assert hub.skip_as_candidate is True
    assert hub.follow_urls
    assert any("gift-cards-bm" in u for u in hub.follow_urls)

    detail = adapter.enrich(
        _selector("the_prize_finder_detail.html"),
        page_url="https://www.theprizefinder.com/competitions/win-1-5-ps200-gift-cards-bm",
    )
    assert detail.skip_as_candidate is False
    assert detail.entry_url is not None
    assert "link-track" in detail.entry_url
    assert detail.restriction_text is not None
    assert "UK" in detail.restriction_text
    assert detail.entry_method_text == "Enter your details"
    a = assess_entry(
        instructions=detail.entry_method_text,
        restriction=detail.restriction_text,
    )
    assert a.eligible_france is False
    assert a.entry_friction == EntryFriction.EASY


def test_the_prize_finder_us_restriction() -> None:
    adapter = ThePrizeFinderAdapter()
    detail = adapter.enrich(
        _selector("the_prize_finder_detail_us.html"),
        page_url="https://www.theprizefinder.com/competitions/win-us-only-package",
    )
    assert infer_eligible_france(restriction=detail.restriction_text) is False


def test_online_competition_adapter() -> None:
    adapter = OnlineCompetitionAdapter()
    listing = adapter.enrich(
        _selector("online_competition_listing.html"),
        page_url="https://www.onlinecompetition.co.uk/",
    )
    assert listing.skip_as_candidate is True
    assert listing.follow_urls

    detail = adapter.enrich(
        _selector("online_competition_detail.html"),
        page_url=(
            "https://www.onlinecompetition.co.uk/competitions/"
            "win-a-salcombe-hotel-break-gin-experience-and-250-clothing-prize/"
        ),
    )
    assert detail.entry_url is not None
    assert "beaufortandblake.com" in detail.entry_url
    assert detail.restriction_text is not None
    assert "UK" in detail.restriction_text
    a = assess_entry(
        instructions=detail.entry_method_text,
        restriction=detail.restriction_text,
        free_hint=True,
        body=detail.excerpt,
    )
    assert a.free_entry is True
    assert a.eligible_france is False
    assert a.entry_friction == EntryFriction.EASY


def test_online_competition_closed_meta() -> None:
    adapter = OnlineCompetitionAdapter()
    detail = adapter.enrich(
        _selector("online_competition_closed.html"),
        page_url="https://www.onlinecompetition.co.uk/competitions/old-competition/",
    )
    assert detail.meta.get("expired") is True


def test_prize_runner_adapter() -> None:
    adapter = PrizeRunnerAdapter()
    listing = adapter.enrich(
        _selector("prize_runner_listing.html"),
        page_url="https://prizerunner.co.uk/",
    )
    assert listing.skip_as_candidate is True
    assert listing.follow_urls
    assert any("wusthof" in u for u in listing.follow_urls)

    detail = adapter.enrich(
        _selector("prize_runner_detail.html"),
        page_url="https://prizerunner.co.uk/2026/09/must-have-knives-from-wusthof",
    )
    assert detail.entry_url == "https://foodism.co.uk/competition/win-wusthof-knives/"
    assert detail.organizer == "Foodism"
    assert detail.entry_method_text == "Website"
    a = assess_entry(
        entry_method_text=detail.entry_method_text,
        body=detail.excerpt,
        free_hint=True,
    )
    assert a.entry_friction == EntryFriction.EASY


def test_contestgirl_decode_and_children() -> None:
    assert (
        decode_contestgirl_url("https://gle!!5m.!!2o/74PCt/w!!2n-!!5-custom-j!!5cket")
        == "https://gleam.io/74PCt/win-a-custom-jacket"
    )
    adapter = ContestGirlAdapter()
    listing = adapter.enrich(
        _selector("contestgirl_listing.html"),
        page_url="https://www.contestgirl.com/contests/contests.pl?f=s&c=us",
    )
    assert listing.skip_as_candidate is True
    assert listing.child_candidates
    first = listing.child_candidates[0]
    assert first.entry_url is not None
    assert "gleam.io" in first.entry_url
    assert "/sweepstakes/" not in first.entry_url
    assert "comment.pl?i=590942" in first.canonical_url


def test_diagnostics_show_international_fields() -> None:
    item = {
        "url": "https://www.theprizefinder.com/competitions/win-demo",
        "title": "Win a demo prize",
        "raw_excerpt": "Enter your details. UK Residents only.",
        "score": 0.8,
        "evidence": {"url_keyword": True, "matched_terms": ["win"]},
        "entry_url": "https://www.theprizefinder.com/link-track?id=1",
        "entry_method": "web_form",
        "entry_friction": "easy",
        "free_entry": True,
        "geo_restriction": "UK Residents only",
        "eligible_france": False,
        "discovery_priority": 4,
    }
    diag = build_candidate_diagnostics(item, source_name="ThePrizeFinder", threshold=0.45)
    text = "\n".join(diag.format_lines())
    assert "source=ThePrizeFinder" in text
    assert "entry_friction=easy" in text
    assert "free=True" in text
    assert "restriction=" in text
    assert "entry_url=" in text
    assert "would_analyze=True" in text
