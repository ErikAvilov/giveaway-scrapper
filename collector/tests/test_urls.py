"""Tests for URL canonicalization."""

from __future__ import annotations

import pytest

from app.urls import canonicalize_url, domain_from_url


def test_strips_utm_and_click_ids() -> None:
    url = (
        "https://Example.com/concours/abc?"
        "utm_source=twitter&utm_medium=social&utm_campaign=spring"
        "&fbclid=IwAR123&gclid=Cj0KCQ&id=42&token=keep-me"
    )
    assert canonicalize_url(url) == "https://example.com/concours/abc?id=42&token=keep-me"


def test_strips_utm_prefix_variants() -> None:
    url = "https://brand.fr/g?utm_foo=1&prize=car"
    assert canonicalize_url(url) == "https://brand.fr/g?prize=car"


def test_preserves_identifying_query_params() -> None:
    url = "https://shop.example/contest?contest_id=99&form=entry&utm_source=x"
    assert canonicalize_url(url) == "https://shop.example/contest?contest_id=99&form=entry"


def test_drops_fragment_and_default_https_port() -> None:
    url = "https://example.com:443/path#section"
    assert canonicalize_url(url) == "https://example.com/path"


def test_keeps_non_default_port() -> None:
    url = "https://example.com:8443/g?utm_campaign=x"
    assert canonicalize_url(url) == "https://example.com:8443/g"


def test_sorts_query_params_for_stability() -> None:
    a = canonicalize_url("https://example.com/g?b=2&a=1")
    b = canonicalize_url("https://example.com/g?a=1&b=2")
    assert a == b == "https://example.com/g?a=1&b=2"


def test_rejects_relative_url() -> None:
    with pytest.raises(ValueError):
        canonicalize_url("/relative/path")


def test_domain_from_url() -> None:
    assert domain_from_url("https://WWW.Example.COM/x") == "www.example.com"
