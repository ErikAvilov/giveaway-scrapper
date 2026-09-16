"""Tests for new France-first discovery adapters and platform parsers."""

from __future__ import annotations

from pathlib import Path

from scrapling.parser import Selector

from app.extraction.france_eligibility import FranceEligibility, classify_france_eligibility
from app.platforms.sweepwidget import (
    parse_sweepwidget_campaign_html,
    parse_sweepwidget_campaign_url,
    sweepwidget_identity_from_url,
)
from app.scraping.adapters import get_adapter, registered_adapter_keys
from app.scraping.adapters.giveaway_base import GiveawayBaseAdapter
from app.scraping.adapters.gleam import GleamAdapter
from app.scraping.adapters.gleam_finder import GleamFinderAdapter
from app.scraping.adapters.gleam_giveaways import GleamGiveawaysAdapter
from app.scraping.adapters.le_demon_du_jeu import LeDemonDuJeuAdapter
from app.scraping.adapters.sweepstakes_bible import SweepstakesBibleAdapter
from app.scraping.adapters.sweepwidget import SweepWidgetAdapter
from app.scraping.adapters.the_prize_finder import ThePrizeFinderAdapter
from app.scraping.adapters.world_free_prizes import WorldFreePrizesAdapter
from app.scraping.diagnostics import summarize_source_candidates
from app.scraping.listing_filters import prefer_listing_card
from app.scraping.seed import load_sources_file

FIXTURES = Path(__file__).parent / "fixtures" / "html"
REAL_SOURCES = Path(__file__).resolve().parents[1] / "config" / "sources.real.json"


def _sel(name: str) -> Selector:
    return Selector((FIXTURES / name).read_text(encoding="utf-8"))


def test_new_adapters_registered() -> None:
    keys = set(registered_adapter_keys())
    for key in (
        "gleam_giveaways",
        "giveaway_base",
        "gleam_finder",
        "sweepwidget",
        "world_free_prizes",
        "sweepstakes_bible",
    ):
        assert key in keys
        assert get_adapter(key) is not None


def test_prefer_listing_card_worldwide_wanted() -> None:
    assert prefer_listing_card(
        geo_text="🌍 Worldwide",
        category_text="Gaming",
        require_worldwide=True,
    )
    assert not prefer_listing_card(
        geo_text="🇺🇸 US",
        category_text="Gaming",
        require_worldwide=True,
    )
    assert not prefer_listing_card(
        geo_text="Worldwide",
        category_text="Travel & Leisure",
        require_worldwide=True,
    )


def test_gleam_giveaways_listing_filters_worldwide() -> None:
    adapter = GleamGiveawaysAdapter()
    listing = adapter.enrich(
        _sel("gleamgiveaways_listing.html"),
        page_url="https://gleamgiveaways.com/",
    )
    assert listing.skip_as_candidate is True
    assert listing.follow_urls
    assert all("/giveaways/" in u for u in listing.follow_urls)


def test_gleam_giveaways_detail_worldwide() -> None:
    adapter = GleamGiveawaysAdapter()
    detail = adapter.enrich(
        _sel("gleamgiveaways_detail_worldwide.html"),
        page_url="https://gleamgiveaways.com/giveaways/steam-deck-oled/",
    )
    assert detail.skip_as_candidate is False
    assert detail.title
    assert detail.restriction_text and "Worldwide" in detail.restriction_text
    assert detail.entry_url and "gleam.io" in detail.entry_url
    assert detail.meta.get("platform") == "gleam"


def test_gleam_giveaways_detail_us_ineligible_locally() -> None:
    adapter = GleamGiveawaysAdapter()
    detail = adapter.enrich(
        _sel("gleamgiveaways_detail_us.html"),
        page_url="https://gleamgiveaways.com/giveaways/tempurpedic/",
    )
    fr = classify_france_eligibility(
        title=detail.title,
        body=detail.excerpt,
        restriction=detail.restriction_text,
    )
    assert fr.france_eligibility == FranceEligibility.INELIGIBLE


def test_giveaway_base_listing_and_worldwide_detail() -> None:
    adapter = GiveawayBaseAdapter()
    listing = adapter.enrich(
        _sel("giveawaybase_listing.html"),
        page_url="https://giveawaybase.com/category/worldwide-2/",
    )
    assert listing.skip_as_candidate is True
    assert listing.follow_urls

    detail = adapter.enrich(
        _sel("giveawaybase_detail.html"),
        page_url="https://giveawaybase.com/steam-frame-giveaway-from-gunman-contracts/",
    )
    assert detail.skip_as_candidate is False
    assert detail.restriction_text and "WORLDWIDE" in detail.restriction_text.upper()
    assert detail.end_date_text
    assert detail.entry_url and "gleam.io" in detail.entry_url
    assert detail.meta.get("platform") == "gleam"


def test_giveaway_base_us_only_skipped() -> None:
    adapter = GiveawayBaseAdapter()
    detail = adapter.enrich(
        _sel("giveawaybase_detail_us.html"),
        page_url="https://giveawaybase.com/us-only-headset-giveaway/",
    )
    assert detail.skip_as_candidate is True


def test_gleam_finder_listing_and_detail() -> None:
    adapter = GleamFinderAdapter()
    listing = adapter.enrich(
        _sel("gleamfinder_listing.html"),
        page_url="https://gleamfinder.com/category/international/",
    )
    assert listing.skip_as_candidate is True
    assert listing.follow_urls

    detail = adapter.enrich(
        _sel("gleamfinder_detail.html"),
        page_url="https://gleamfinder.com/giveaway/mRy8w/fall-sale-warmup-giveaway",
    )
    assert detail.entry_url and "gleam.io" in detail.entry_url
    assert detail.restriction_text and "Worldwide" in detail.restriction_text
    assert detail.meta.get("platform") == "gleam"
    assert detail.meta.get("platform_campaign_id") == "mRy8w"


def test_sweepwidget_platform_parser() -> None:
    cid, slug = parse_sweepwidget_campaign_url(
        "https://sweepwidget.com/giveaways/101938-ew16zxym"
    )
    assert cid == "101938"
    assert slug == "ew16zxym"
    identity = sweepwidget_identity_from_url(
        "https://sweepwidget.com/c/101938-ew16zxym"
    )
    assert identity and identity["platform"] == "sweepwidget"

    html = (FIXTURES / "sweepwidget_campaign_worldwide.html").read_text(encoding="utf-8")
    campaign = parse_sweepwidget_campaign_html(
        html,
        page_url="https://sweepwidget.com/giveaways/101938-ew16zxym",
    )
    assert campaign is not None
    assert campaign.geo_restriction and "worldwide" in campaign.geo_restriction.lower()


def test_sweepwidget_adapter_directory_and_campaign() -> None:
    adapter = SweepWidgetAdapter()
    listing = adapter.enrich(
        _sel("sweepwidget_listing.html"),
        page_url="https://sweepwidget.com/giveaways/?sort=latest",
    )
    assert listing.skip_as_candidate is True
    assert listing.follow_urls

    detail = adapter.enrich(
        _sel("sweepwidget_campaign_worldwide.html"),
        page_url="https://sweepwidget.com/giveaways/101938-ew16zxym",
    )
    assert detail.skip_as_candidate is False
    assert detail.meta.get("platform") == "sweepwidget"
    assert detail.meta.get("platform_campaign_id") == "101938"
    # Geo present → eligible; missing geo must stay unknown (covered below).
    fr = classify_france_eligibility(
        title=detail.title,
        body=detail.excerpt,
        restriction=detail.restriction_text,
    )
    assert fr.france_eligibility == FranceEligibility.ELIGIBLE


def test_sweepwidget_missing_geo_stays_unknown() -> None:
    adapter = SweepWidgetAdapter()
    detail = adapter.enrich(
        _sel("sweepwidget_campaign.html"),
        page_url="https://sweepwidget.com/giveaways/101938-ew16zxym",
    )
    fr = classify_france_eligibility(
        title=detail.title,
        body=detail.excerpt,
        restriction=detail.restriction_text,
    )
    assert fr.france_eligibility == FranceEligibility.UNKNOWN


def test_gleam_directory_discovers_campaigns() -> None:
    adapter = GleamAdapter()
    listing = adapter.enrich(
        _sel("gleam_directory.html"),
        page_url="https://gleam.io/giveaways",
    )
    assert listing.skip_as_candidate is True
    assert listing.follow_urls
    assert any("/Ab12Cd/" in u for u in listing.follow_urls)
    assert all("pricing" not in u for u in listing.follow_urls)


def test_world_free_prizes_worldwide_and_us() -> None:
    adapter = WorldFreePrizesAdapter()
    listing = adapter.enrich(
        _sel("worldfreeprizes_listing.html"),
        page_url="https://www.worldfreeprizes.com/country/worldwide/",
    )
    assert listing.skip_as_candidate is True
    assert listing.follow_urls

    ww = adapter.enrich(
        _sel("worldfreeprizes_detail.html"),
        page_url="https://www.worldfreeprizes.com/giveaways/playstation-pro-grand-theft-auto-giveaway-gleam/",
    )
    assert ww.skip_as_candidate is False
    fr = classify_france_eligibility(
        title=ww.title, body=ww.excerpt, restriction=ww.restriction_text
    )
    assert fr.france_eligibility == FranceEligibility.ELIGIBLE

    us = adapter.enrich(
        _sel("worldfreeprizes_detail_us.html"),
        page_url="https://www.worldfreeprizes.com/giveaways/callaway-golf-gift-card-sweepstakes/",
    )
    fr_us = classify_france_eligibility(
        title=us.title, body=us.excerpt, restriction=us.restriction_text
    )
    assert fr_us.france_eligibility == FranceEligibility.INELIGIBLE


def test_sweepstakes_bible_travel_skipped() -> None:
    adapter = SweepstakesBibleAdapter()
    listing = adapter.enrich(
        _sel("sweepstakesbible_listing.html"),
        page_url="https://www.sweepstakesbible.com/tags/worldwide",
    )
    assert listing.skip_as_candidate is True
    assert listing.follow_urls

    cash = adapter.enrich(
        _sel("sweepstakesbible_detail.html"),
        page_url="https://www.sweepstakesbible.com/giveaways/325-cash-giveaway",
    )
    assert cash.skip_as_candidate is False
    assert cash.restriction_text == "Worldwide"

    travel = adapter.enrich(
        _sel("sweepstakesbible_detail_travel.html"),
        page_url="https://www.sweepstakesbible.com/giveaways/hawaii-trip",
    )
    assert travel.skip_as_candidate is True


def test_tpf_worldwide_listing_and_detail() -> None:
    adapter = ThePrizeFinderAdapter()
    listing = adapter.enrich(
        _sel("tpf_worldwide_listing.html"),
        page_url="https://www.theprizefinder.com/search/competitions?keys=worldwide",
    )
    assert listing.skip_as_candidate is True
    assert listing.follow_urls
    assert any("worldwide-gaming-pc" in u for u in listing.follow_urls)
    assert all("uk-only-holiday" not in u for u in listing.follow_urls)

    detail = adapter.enrich(
        _sel("tpf_worldwide_detail.html"),
        page_url="https://www.theprizefinder.com/competitions/worldwide-gaming-pc",
    )
    assert detail.skip_as_candidate is False
    assert detail.restriction_text and "Worldwide" in detail.restriction_text


def test_le_demon_france_resident_phrase() -> None:
    adapter = LeDemonDuJeuAdapter()
    detail = adapter.enrich(
        _sel("le_demon_du_jeu_france_detail.html"),
        page_url="https://www.ledemondujeu.com/jeux-concours-smartphone.html",
    )
    assert detail.restriction_text
    fr = classify_france_eligibility(
        title=detail.title,
        body=detail.excerpt,
        restriction=detail.restriction_text,
    )
    assert fr.france_eligibility == FranceEligibility.ELIGIBLE
    assert fr.eligible_france is True


def test_real_sources_france_first_enabled_set() -> None:
    rows = load_sources_file(REAL_SOURCES)
    enabled = {r["name"] for r in rows if r.get("enabled")}
    assert "GleamGiveaways" in enabled
    assert "GiveawayBase" in enabled
    assert "GleamFinder International" in enabled
    assert "SweepWidget Directory" in enabled
    assert "WorldFreePrizes Worldwide" in enabled
    assert "ThePrizeFinder Worldwide" in enabled
    assert "SweepstakesBible Worldwide" in enabled
    assert "Le Démon du Jeu High-Tech" in enabled
    assert "Concours.fr High-Tech" in enabled
    disabled = {r["name"]: r for r in rows if not r.get("enabled")}
    for name in (
        "Giveario US",
        "Giveario UK",
        "ContestGirl",
        "OnlineCompetitions",
        "PrizeRunner",
        "ThePrizeFinder RSS",
    ):
        assert name in disabled
        assert disabled[name]["crawl_config"].get("enabled_reason") in {
            "country_incompatible",
            "unsupported",
            "superseded",
        }


def test_summarize_source_candidates_counts() -> None:
    candidates = [
        {
            "france_eligibility": "eligible",
            "eligible_france": True,
            "wanted_prize": True,
            "status": "candidate",
            "score": 0.9,
            "url": "https://example.com/a",
            "platform": "gleam",
            "platform_campaign_id": "aaa",
            "raw_excerpt": "Win a PS5 worldwide",
            "title": "PS5",
        },
        {
            "france_eligibility": "ineligible",
            "eligible_france": False,
            "wanted_prize": True,
            "status": "rejected",
            "score": 0.9,
            "url": "https://example.com/b",
            "raw_excerpt": "US only",
            "title": "US",
        },
        {
            "france_eligibility": "eligible",
            "eligible_france": True,
            "wanted_prize": True,
            "status": "candidate",
            "score": 0.9,
            "url": "https://example.com/c",
            "platform": "gleam",
            "platform_campaign_id": "aaa",
            "raw_excerpt": "dup",
            "title": "dup",
        },
    ]
    summary = summarize_source_candidates(
        source_name="GiveawayBase",
        pages_fetched=10,
        candidates=candidates,
        threshold=0.45,
    )
    assert summary.france_eligible == 2
    assert summary.france_ineligible == 1
    assert summary.duplicates == 1
    assert summary.wanted == 3
