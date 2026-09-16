"""Tests for URL follow filtering."""

from __future__ import annotations

from app.scraping.filters import is_asset_url, should_follow_url


def test_allows_same_domain_http() -> None:
    assert should_follow_url(
        "https://brand.example/concours/1",
        allowed_domains={"brand.example"},
    )


def test_rejects_offsite() -> None:
    assert not should_follow_url(
        "https://other.example/page",
        allowed_domains={"brand.example"},
    )


def test_rejects_assets_and_mailto() -> None:
    assert is_asset_url("https://brand.example/static/app.js")
    assert not should_follow_url(
        "https://brand.example/logo.png",
        allowed_domains={"brand.example"},
    )
    assert not should_follow_url(
        "mailto:hello@brand.example",
        allowed_domains={"brand.example"},
    )


def test_rejects_social_hosts() -> None:
    assert not should_follow_url(
        "https://twitter.com/share?url=https://brand.example",
        allowed_domains={"brand.example", "twitter.com"},
    )
    # Even if mistakenly allowed, blocked host wins when checking social
    assert not should_follow_url(
        "https://facebook.com/brand",
        allowed_domains={"facebook.com"},
    )
