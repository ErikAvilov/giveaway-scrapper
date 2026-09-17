"""Regression: boilerplate must not poison crypto/referral filters."""

from __future__ import annotations

from pathlib import Path

from scrapling.parser import Selector

from app.extraction.entry_acceptability import assess_entry_acceptability
from app.extraction.entry_assessment import EntryFriction, assess_entry, detect_undesirable
from app.platforms.gleam import GleamEntryAction, assess_gleam_friction
from app.scraping.adapters.gleam_giveaways import GleamGiveawaysAdapter
from app.scraping.diagnostics import build_candidate_diagnostics
from app.scraping.seed import load_sources_file

FIXTURES = Path(__file__).parent / "fixtures" / "html"
REAL_SOURCES = Path(__file__).resolve().parents[1] / "config" / "sources.real.json"


def _sel(name: str) -> Selector:
    return Selector((FIXTURES / name).read_text(encoding="utf-8"))


def test_nav_crypto_does_not_flag_back_massager() -> None:
    adapter = GleamGiveawaysAdapter()
    detail = adapter.enrich(
        _sel("gleamgiveaways_detail_massager.html"),
        page_url="https://gleamgiveaways.com/giveaways/back-massager",
    )
    assert detail.title and "Massager" in detail.title
    assert "Crypto" not in (detail.excerpt or "")
    assessment = assess_entry(
        title=detail.title,
        prize=detail.prize,
        body=detail.excerpt,
        category=(detail.meta or {}).get("category"),
        restriction=detail.restriction_text,
    )
    assert "crypto" not in assessment.skip_reasons
    assert assessment.skip_gemini is False
    reasons = detect_undesirable(
        title=detail.title,
        prize=detail.prize,
        category=(detail.meta or {}).get("category"),
        body=detail.excerpt,
    )
    assert "crypto" not in reasons


def test_sitewide_crypto_link_does_not_flag_charging_dock() -> None:
    adapter = GleamGiveawaysAdapter()
    detail = adapter.enrich(
        _sel("gleamgiveaways_detail_charging_dock.html"),
        page_url="https://gleamgiveaways.com/giveaways/charging-dock",
    )
    assessment = assess_entry(
        title=detail.title,
        prize=detail.prize,
        body=detail.excerpt,
        category=(detail.meta or {}).get("category"),
    )
    assert "crypto" not in assessment.skip_reasons
    diag = build_candidate_diagnostics(
        {
            "title": detail.title,
            "raw_excerpt": detail.excerpt,
            "score": 0.7,
            "skip_analyze": assessment.skip_gemini,
            "skip_reasons": list(assessment.skip_reasons),
            "url": "https://gleamgiveaways.com/giveaways/charging-dock",
            "eligible_france": True,
            "wanted_prize": True,
        },
        source_name="GleamGiveaways",
        threshold=0.45,
    )
    assert diag.would_analyze is True
    assert not any(s.startswith("filter:crypto") for s in diag.negative_signals)


def test_real_crypto_giveaway_still_filtered() -> None:
    adapter = GleamGiveawaysAdapter()
    detail = adapter.enrich(
        _sel("gleamgiveaways_detail_crypto.html"),
        page_url="https://gleamgiveaways.com/giveaways/bitcoin-airdrop",
    )
    assessment = assess_entry(
        title=detail.title,
        prize=detail.prize,
        body=detail.excerpt,
        category=(detail.meta or {}).get("category"),
    )
    assert "crypto" in assessment.skip_reasons
    assert assessment.skip_gemini is True


def test_optional_referral_does_not_reject() -> None:
    assessment = assess_entry(
        title="PlayStation Pro + Grand Theft Auto Giveaway",
        body=(
            "Prize: PlayStation Pro + Grand Theft Auto\n"
            "Optional: referral\n"
            "referral:refer_friend\n"
            "Get +5 bonus entries for referrals"
        ),
        instructions="optional:referral; mandatory:visit_website,email_subscribe",
        prize="PlayStation Pro + Grand Theft Auto",
    )
    assert "referrals" not in assessment.skip_reasons
    assert assessment.skip_gemini is False

    gate = assess_entry_acceptability(
        title="PlayStation Pro + Grand Theft Auto Giveaway",
        prize="PlayStation Pro",
        platform_actions=[
            {"entry_type": "visit_website", "mandatory": True},
            {"entry_type": "email_subscribe", "mandatory": True},
            {"entry_type": "referral", "mandatory": False},
            {"entry_type": "instagram_comment", "mandatory": False},
        ],
    )
    assert gate.entry_acceptable is True
    assert gate.requires_public_social_action is False


def test_optional_public_social_does_not_reject() -> None:
    gate = assess_entry_acceptability(
        platform_actions=[
            {"entry_type": "instagram_follow", "mandatory": True},
            {"entry_type": "instagram_comment", "mandatory": False},
            {"entry_type": "share_action", "mandatory": False},
        ]
    )
    assert gate.entry_acceptable is True


def test_gleam_optional_referral_not_hard_friction() -> None:
    friction = assess_gleam_friction(
        actions_required=1,
        mandatory=[
            GleamEntryAction(entry_type="visit_website", mandatory=True, category="visit"),
        ],
        optional=[
            GleamEntryAction(entry_type="referral", mandatory=False, category="referral"),
        ],
        login_required=False,
        has_paid=False,
    )
    assert friction != EntryFriction.HARD


def test_official_gleam_directory_seeded_enabled() -> None:
    rows = load_sources_file(REAL_SOURCES)
    by_name = {r["name"]: r for r in rows}
    assert "Gleam Official Directory" in by_name
    src = by_name["Gleam Official Directory"]
    assert src["enabled"] is True
    assert src["base_url"].rstrip("/").endswith("gleam.io/giveaways")
    assert src["crawl_config"]["adapter"] == "gleam"
    assert src["crawl_config"]["profile"] == "real"
