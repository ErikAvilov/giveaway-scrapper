"""Tests for real-source seeding, adapters, diagnostics, and --real-test limits."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from click.testing import CliRunner
from scrapling.parser import Selector

from app.cli import main
from app.config import Settings
from app.db.connection import connection
from app.models.source import SourceType
from app.scraping.adapters import get_adapter, registered_adapter_keys
from app.scraping.adapters.concours_du_net import ConcoursDuNetAdapter
from app.scraping.adapters.concours_fr import ConcoursFrAdapter
from app.scraping.adapters.echantillonsclub import EchantillonsClubAdapter
from app.scraping.adapters.le_demon_du_jeu import LeDemonDuJeuAdapter
from app.scraping.adapters.mes_echantillons_gratuits import MesEchantillonsGratuitsAdapter
from app.scraping.diagnostics import build_candidate_diagnostics
from app.scraping.real_test import (
    REAL_TEST_MAX_DEPTH,
    REAL_TEST_MAX_PAGES,
    apply_real_test_limits,
    is_real_profile,
)
from app.scraping.seed import load_sources_file, seed_sources
from app.scraping.spider import SpiderLimits, build_spider

FIXTURES = Path(__file__).parent / "fixtures" / "html"
REAL_SOURCES = Path(__file__).resolve().parents[1] / "config" / "sources.real.json"


def _selector(name: str) -> Selector:
    return Selector((FIXTURES / name).read_text(encoding="utf-8"))


def test_real_sources_file_has_french_and_international() -> None:
    rows = load_sources_file(REAL_SOURCES)
    assert len(rows) >= 12
    enabled = [r for r in rows if r.get("enabled")]
    disabled = [r for r in rows if not r.get("enabled")]
    enabled_names = {r["name"] for r in enabled}
    assert "GleamGiveaways" in enabled_names
    assert "GiveawayBase" in enabled_names
    assert "GleamFinder International" in enabled_names
    assert "SweepWidget Directory" in enabled_names
    assert "Gleam Official Directory" in enabled_names
    assert "WorldFreePrizes Worldwide" in enabled_names
    assert "ThePrizeFinder Worldwide" in enabled_names
    assert "SweepstakesBible Worldwide" in enabled_names
    assert "Concours du Net" in enabled_names
    assert "Le Démon du Jeu High-Tech" in enabled_names
    assert "Concours.fr High-Tech" in enabled_names
    assert "Mes Échantillons Gratuits" in enabled_names
    assert "ÉchantillonsClub" in enabled_names
    disabled_names = {r["name"] for r in disabled}
    assert {
        "Giveario US",
        "Giveario UK",
        "ThePrizeFinder RSS",
        "OnlineCompetitions",
        "PrizeRunner",
        "ContestGirl",
        "GiveawayListing",
        "FelixCompetitions",
    }.issubset(disabled_names)
    by_name = {r["name"]: r for r in rows}
    for name in (
        "Giveario US",
        "Giveario UK",
        "ThePrizeFinder RSS",
        "OnlineCompetitions",
        "PrizeRunner",
        "ContestGirl",
    ):
        assert by_name[name]["crawl_config"].get("enabled_reason") == "country_incompatible"
    for fr_name in (
        "Concours du Net",
        "Le Démon du Jeu High-Tech",
        "Concours.fr High-Tech",
        "Mes Échantillons Gratuits",
        "ÉchantillonsClub",
    ):
        assert by_name[fr_name]["crawl_config"]["target_regions"] == [
            "france",
            "eu",
            "worldwide",
        ]
    gleam = by_name["Gleam Official Directory"]
    assert gleam["enabled"] is True
    assert gleam["source_type"] == "other"
    assert gleam["crawl_config"]["adapter"] == "gleam"
    assert gleam["crawl_config"]["profile"] == "real"
    assert gleam["crawl_config"]["target_regions"] == ["worldwide", "france", "eu"]
    assert "gleam.io/giveaways" in gleam["base_url"]
    assert int(gleam["crawl_config"].get("gleam_directory_max_pages") or 0) >= 1
    assert int(gleam["crawl_config"].get("max_depth") or 0) >= 2
    assert all(
        r["source_type"] in {"giveaway_aggregator", "other"} for r in rows
    )
    assert all(r["crawl_config"]["profile"] == "real" for r in rows)
    for r in enabled:
        adapter = r["crawl_config"].get("adapter")
        assert adapter in registered_adapter_keys()
    urls = {r["base_url"] for r in rows}
    assert "https://www.concours-du-net.com/" in urls
    assert "https://giveario.com/en/countries/united-states/" in urls
    assert "https://www.theprizefinder.com/rss.xml" in urls
    assert "https://gleamgiveaways.com/" in urls
    assert "https://giveawaybase.com/category/worldwide-2/" in urls
    regions = {r["crawl_config"].get("region") for r in enabled}
    assert "france" in regions
    assert "international" in regions


def test_seed_real_sources(settings: Settings, migrated_db) -> None:
    with connection(settings) as conn:
        seeded = seed_sources(conn, REAL_SOURCES)
        conn.commit()
        enabled = [s for s in seeded if s.enabled]
        assert len(seeded) >= 12
        assert len(enabled) >= 13
        assert {s.name for s in seeded} >= {
            "GleamGiveaways",
            "GiveawayBase",
            "Gleam Official Directory",
        }
        official = next(s for s in seeded if s.name == "Gleam Official Directory")
        assert official.enabled is True
        assert "gleam.io/giveaways" in str(official.base_url)
        assert all(
            s.source_type
            in {SourceType.GIVEAWAY_AGGREGATOR, SourceType.OTHER}
            for s in seeded
        )
        assert all(is_real_profile(s.crawl_config) for s in seeded)
        again = seed_sources(conn, REAL_SOURCES)
        conn.commit()
        assert {str(s.base_url) for s in again} == {str(s.base_url) for s in seeded}


def test_adapter_registry() -> None:
    assert get_adapter("concours_du_net") is not None
    assert get_adapter("giveario") is not None
    assert get_adapter("the_prize_finder") is not None
    assert get_adapter("missing") is None
    keys = set(registered_adapter_keys())
    assert {
        "concours_du_net",
        "le_demon_du_jeu",
        "concours_fr",
        "mes_echantillons_gratuits",
        "echantillonsclub",
        "giveario",
        "the_prize_finder",
        "online_competition",
        "prize_runner",
        "contestgirl",
        "gleam",
        "gleam_giveaways",
        "giveaway_base",
        "gleam_finder",
        "sweepwidget",
        "world_free_prizes",
        "sweepstakes_bible",
    }.issubset(keys)


def test_concours_du_net_listing_and_detail_fixtures() -> None:
    adapter = ConcoursDuNetAdapter()
    listing = adapter.enrich(
        _selector("concours_du_net_listing.html"),
        page_url="https://www.concours-du-net.com/",
    )
    assert listing.skip_as_candidate is True
    assert listing.follow_urls
    assert any("/jeu-concours-" in u for u in listing.follow_urls)

    detail = adapter.enrich(
        _selector("concours_du_net_detail.html"),
        page_url="https://www.concours-du-net.com/jeu-concours-kadolis-95148495609b82ed",
    )
    assert detail.skip_as_candidate is False
    assert detail.entry_url is not None
    assert "track.php" in detail.entry_url


def test_le_demon_du_jeu_fixtures() -> None:
    adapter = LeDemonDuJeuAdapter()
    listing = adapter.enrich(
        _selector("le_demon_du_jeu_listing.html"),
        page_url="https://www.ledemondujeu.com/",
    )
    assert listing.skip_as_candidate is True
    assert listing.follow_urls

    detail = adapter.enrich(
        _selector("le_demon_du_jeu_detail.html"),
        page_url="https://www.ledemondujeu.com/jeux-concours-autosur.fr.html",
    )
    assert detail.skip_as_candidate is False
    assert detail.entry_url is not None
    assert "toconc" in detail.entry_url


def test_concours_fr_fixtures() -> None:
    adapter = ConcoursFrAdapter()
    listing = adapter.enrich(
        _selector("concours_fr_listing.html"),
        page_url="https://www.concours.fr/",
    )
    assert listing.skip_as_candidate is True
    assert listing.follow_urls

    detail = adapter.enrich(
        _selector("concours_fr_detail.html"),
        page_url="https://www.concours.fr/tentez-de-remporter-un-casque-bose-quietcomfort/",
    )
    assert detail.skip_as_candidate is False
    assert detail.entry_url is not None
    assert "instagram.com" in detail.entry_url or detail.entry_url.startswith("http")


def test_meg_fixtures() -> None:
    adapter = MesEchantillonsGratuitsAdapter()
    listing = adapter.enrich(
        _selector("meg_listing.html"),
        page_url="https://www.mesechantillonsgratuits.fr/jeux-concours/",
    )
    assert listing.skip_as_candidate is True
    assert listing.follow_urls

    detail = adapter.enrich(
        _selector("meg_detail.html"),
        page_url=(
            "https://www.mesechantillonsgratuits.fr/jeux-concours/"
            "gagnez-un-coffret-de-18-brumes-adopt-parfums-de-26910-e-ou-lun-des-501-autres-lots/"
        ),
    )
    assert detail.skip_as_candidate is False
    assert detail.entry_url is not None
    assert "mesechantillonsgratuits.fr" not in detail.entry_url


def test_echantillonsclub_fixtures_skip_expired_and_store_entry() -> None:
    adapter = EchantillonsClubAdapter()
    listing = adapter.enrich(
        _selector("echantillonsclub_listing.html"),
        page_url="https://www.echantillonsclub.com/concours",
    )
    assert listing.skip_as_candidate is True
    assert listing.follow_urls
    # Expired cards must not be followed.
    assert all("iexpired" not in u for u in listing.follow_urls)

    detail = adapter.enrich(
        _selector("echantillonsclub_detail.html"),
        page_url="https://www.echantillonsclub.com/220582-jeu-gratuit-lebonnumero.html",
    )
    assert detail.skip_as_candidate is False
    assert detail.entry_url is not None
    assert "/url/" in detail.entry_url


def test_diagnostics_positive_and_negative_signals() -> None:
    item = {
        "url": "https://example.com/jeu-concours-test",
        "title": "Jeu concours gratuit",
        "raw_excerpt": "Participez avant la date limite. Concours cloture demain.",
        "score": 0.72,
        "evidence": {
            "url_keyword": True,
            "title_keyword": True,
            "matched_terms": ["jeu concours", "gratuit"],
            "content_strong_hits": 2,
            "has_entry_language": True,
        },
        "entry_url": "https://brand.example/play",
    }
    diag = build_candidate_diagnostics(item, source_name="TestSrc", threshold=0.45)
    assert diag.would_analyze is True
    assert any(s.startswith("term:") or s == "url_keyword" for s in diag.positive_signals)
    assert any("cloture" in s or "phrase:" in s for s in diag.negative_signals)
    text = "\n".join(diag.format_lines())
    assert "would_analyze=True" in text
    assert "TestSrc" in text


def test_real_test_limits_are_hard_capped(settings: Settings) -> None:
    generous = SpiderLimits(
        max_depth=5,
        max_pages=200,
        candidate_threshold=0.45,
        excerpt_max_chars=3000,
        request_timeout=20.0,
        retries=2,
    )
    capped = apply_real_test_limits(generous, settings)
    assert capped.max_pages == REAL_TEST_MAX_PAGES
    assert capped.max_depth == REAL_TEST_MAX_DEPTH


def test_build_spider_wires_adapter() -> None:
    spider = build_spider(
        source_id=uuid4(),
        start_url="https://www.concours-du-net.com/",
        allowed_domain="concours-du-net.com",
        concurrent_requests=2,
        concurrent_requests_per_domain=1,
        download_delay=1.0,
        autothrottle=True,
        autothrottle_start_delay=1.0,
        autothrottle_max_delay=30.0,
        limits=SpiderLimits(1, 10, 0.45, 3000, 20.0, 2),
        adapter_key="concours_du_net",
        source_name="Concours du Net",
    )
    assert spider.adapter is not None
    assert spider.adapter.key == "concours_du_net"
    assert spider.concurrent_requests == 2
    assert spider.concurrent_requests_per_domain == 1
    assert spider.robots_txt_obey is False


def test_crawl_real_test_never_instantiates_gemini(settings: Settings, migrated_db) -> None:
    """crawl --real-test must not touch GeminiClient."""
    with connection(settings) as conn:
        seed_sources(conn, REAL_SOURCES)
        conn.commit()

    runner = CliRunner()
    with (
        patch("app.scraping.runner.run_spider") as run_spider,
        patch("app.gemini.client.GeminiClient", autospec=True) as gemini_cls,
        patch("app.gemini.service.GeminiClient", autospec=True) as gemini_svc,
    ):
        run_spider.return_value = (
            [
                {
                    "kind": "candidate",
                    "url": "https://www.concours-du-net.com/jeu-concours-demo",
                    "original_url": "https://www.concours-du-net.com/jeu-concours-demo",
                    "title": "Demo concours",
                    "raw_excerpt": "Jeu concours gratuit date limite participer",
                    "link_hints": [],
                    "entry_url": "https://brand.example/play",
                    "score": 0.8,
                    "evidence": {"url_keyword": True, "matched_terms": ["concours"]},
                }
            ],
            {"pages_fetched_local": 2, "failed_requests_count": 0, "blocked_requests_count": 0},
        )
        result = runner.invoke(main, ["crawl", "--real-test", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Would analyze:" in result.output
    assert "TOTAL" in result.output
    assert "Gemini not invoked" in result.output
    gemini_cls.assert_not_called()
    gemini_svc.assert_not_called()
    # Enabled France-first discovery sources (aggregators + platform directories).
    assert run_spider.call_count >= 13
    assert "Worldwide/France:" in result.output or "Would analyze:" in result.output


def test_cli_help_lists_seed_and_real_test() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "seed" in result.output
    crawl_help = runner.invoke(main, ["crawl", "--help"])
    assert "--real-test" in crawl_help.output
