"""Tests for Gleam enter URL resolution and queue matching."""

from __future__ import annotations

from uuid import uuid4

from app.gleam_enter.service import _job_matched, _parse_bot_summary
from app.gleam_enter.urls import gleam_entry_url
from app.models.giveaway import Giveaway, GiveawayStatus, ManualStatus


def _g(**kwargs) -> Giveaway:
    base = {
        "canonical_url": "https://gleam.io/gB6Mc/ps5",
        "original_url": "https://gleam.io/gB6Mc/ps5",
        "domain": "gleam.io",
        "content_hash": "abc",
        "status": GiveawayStatus.ACTIVE,
        "manual_status": ManualStatus.INTERESTED,
        "platform": "gleam",
        "platform_campaign_id": "gB6Mc",
        "entry_url": "https://gleam.io/gB6Mc/ps5",
    }
    base.update(kwargs)
    return Giveaway(**base)


def test_gleam_entry_url_prefers_classic() -> None:
    g = _g()
    assert gleam_entry_url(g) == "https://gleam.io/gB6Mc/ps5"


def test_gleam_entry_url_from_campaign_id() -> None:
    g = _g(entry_url=None)
    assert gleam_entry_url(g) == "https://gleam.io/gB6Mc/x"


def test_gleam_entry_url_directory_shell() -> None:
    g = _g(entry_url="https://gleam.io/giveaways/gB6Mc")
    assert gleam_entry_url(g) == "https://gleam.io/gB6Mc/x"


def test_parse_bot_summary_last_json() -> None:
    stdout = "noise\n{\"attempted\": 1, \"ok\": [{\"id\": \"gB6Mc\"}], \"failed\": []}\n"
    data = _parse_bot_summary(stdout)
    assert data is not None
    assert data["attempted"] == 1
    assert data["ok"][0]["id"] == "gB6Mc"


def test_job_matched_by_campaign_id() -> None:
    g = _g(id=uuid4())
    assert _job_matched(
        g,
        "https://gleam.io/gB6Mc/x",
        [{"id": "gB6Mc", "url": "https://gleam.io/gB6Mc/a"}],
    )
