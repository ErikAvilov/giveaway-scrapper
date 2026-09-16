"""Tests for Gleam.io platform parser (HTTP-extractable campaign metadata)."""

from __future__ import annotations

from pathlib import Path

from scrapling.parser import Selector

from app.extraction.entry_assessment import EntryFriction
from app.platforms.gleam import (
    GleamEntryAction,
    assess_gleam_friction,
    gleam_identity_from_url,
    parse_gleam_campaign_html,
    parse_gleam_campaign_url,
)
from app.scraping.adapters import get_adapter, registered_adapter_keys
from app.scraping.adapters.gleam import GleamAdapter

FIXTURES = Path(__file__).parent / "fixtures" / "html"


def test_gleam_url_identity() -> None:
    key, slug = parse_gleam_campaign_url(
        "https://gleam.io/74PCt/win-a-custom-windwaker-x-violent-gentlemen-jacket"
    )
    assert key == "74PCt"
    assert slug and slug.startswith("win-a-custom")
    identity = gleam_identity_from_url("https://gleam.io/74PCt/win-a-jacket")
    assert identity is not None
    assert identity["platform"] == "gleam"
    assert identity["platform_campaign_id"] == "74PCt"
    assert identity["entry_url"].startswith("https://gleam.io/74PCt/")
    assert parse_gleam_campaign_url("https://gleam.io/app/competitions") == (None, None)
    assert parse_gleam_campaign_url("https://example.com/74PCt/x") == (None, None)


def test_gleam_easy_fixture() -> None:
    html = (FIXTURES / "gleam_easy.html").read_text(encoding="utf-8")
    campaign = parse_gleam_campaign_html(
        html, page_url="https://gleam.io/Easy1/win-easy-prize"
    )
    assert campaign is not None
    assert campaign.platform == "gleam"
    assert campaign.platform_campaign_id == "Easy1"
    assert campaign.title == "Win Easy Prize"
    assert campaign.organizer == "EasyBrand"
    assert campaign.entry_friction == EntryFriction.EASY.value
    assert campaign.free_entry is True
    assert campaign.eligible_france is True
    assert campaign.geo_restriction == "Worldwide"
    assert campaign.start_at is not None
    assert campaign.end_at is not None
    assert any(a.entry_type == "email_subscribe" for a in campaign.mandatory_actions)
    assert campaign.actions_required == 1
    meta = campaign.to_meta()
    assert meta["platform"] == "gleam"
    assert meta["platform_campaign_id"] == "Easy1"


def test_gleam_medium_fixture() -> None:
    html = (FIXTURES / "gleam_medium.html").read_text(encoding="utf-8")
    campaign = parse_gleam_campaign_html(
        html, page_url="https://gleam.io/Med12/win-medium-prize"
    )
    assert campaign is not None
    assert campaign.entry_friction == EntryFriction.MEDIUM.value
    assert campaign.login_required is True
    assert campaign.eligible_france is False
    assert len(campaign.social_actions) >= 3


def test_gleam_hard_referral_upload_fixture() -> None:
    html = (FIXTURES / "gleam_hard.html").read_text(encoding="utf-8")
    campaign = parse_gleam_campaign_html(
        html, page_url="https://gleam.io/Hard9/win-hard-prize"
    )
    assert campaign is not None
    assert campaign.entry_friction == EntryFriction.HARD.value
    assert campaign.referral_actions
    assert campaign.upload_actions
    assert campaign.eligible_france is False


def test_assess_gleam_friction_helpers() -> None:
    easy = assess_gleam_friction(
        actions_required=1,
        mandatory=[
            GleamEntryAction(entry_type="email_subscribe", mandatory=True, category="email")
        ],
        optional=[],
        login_required=False,
        has_paid=False,
    )
    assert easy == EntryFriction.EASY
    hard = assess_gleam_friction(
        actions_required=1,
        mandatory=[GleamEntryAction(entry_type="referral", mandatory=True, category="referral")],
        optional=[],
        login_required=False,
        has_paid=False,
    )
    assert hard == EntryFriction.HARD


def test_gleam_adapter_enrich() -> None:
    adapter = GleamAdapter()
    assert adapter.key == "gleam"
    assert "gleam" in registered_adapter_keys()
    assert get_adapter("gleam") is not None

    page = Selector((FIXTURES / "gleam_easy.html").read_text(encoding="utf-8"))
    enrichment = adapter.enrich(
        page, page_url="https://gleam.io/Easy1/win-easy-prize"
    )
    assert enrichment.skip_as_candidate is False
    assert enrichment.title == "Win Easy Prize"
    assert enrichment.entry_url == "https://gleam.io/Easy1/win-easy-prize"
    assert enrichment.meta.get("platform") == "gleam"
    assert enrichment.meta.get("platform_campaign_id") == "Easy1"
    assert enrichment.meta.get("entry_friction_override") == "easy"
    assert enrichment.restriction_text == "Worldwide"


def test_contestgirl_child_gets_gleam_platform_meta() -> None:
    from app.scraping.adapters.contestgirl import ContestGirlAdapter

    adapter = ContestGirlAdapter()
    listing = adapter.enrich(
        Selector((FIXTURES / "contestgirl_listing.html").read_text(encoding="utf-8")),
        page_url="https://www.contestgirl.com/contests/contests.pl?f=s&c=us",
    )
    assert listing.child_candidates
    gleam_child = next(
        c for c in listing.child_candidates if c.entry_url and "gleam.io" in c.entry_url
    )
    assert gleam_child.meta.get("platform") == "gleam"
    assert gleam_child.meta.get("platform_campaign_id")
