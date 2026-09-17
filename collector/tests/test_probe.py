"""Unit tests for ad-hoc URL probe helpers."""

from __future__ import annotations

import pytest

from app.scraping.probe import (
    build_probe_config,
    ephemeral_source,
    normalize_probe_url,
)


def test_normalize_probe_url_adds_https() -> None:
    assert normalize_probe_url("example.com") == "https://example.com/"
    assert normalize_probe_url("https://example.com/path") == "https://example.com/path"


def test_build_probe_config_rejects_unknown_adapter() -> None:
    with pytest.raises(ValueError, match="Unknown adapter"):
        build_probe_config(adapter="not_a_real_adapter")


def test_build_probe_config_merges_json() -> None:
    cfg = build_probe_config(
        adapter=None,
        max_pages=3,
        config_json={"adapter": "gleam", "max_pages": 5, "max_depth": 0},
    )
    assert cfg.adapter == "gleam"
    assert cfg.max_pages == 5
    assert cfg.max_depth == 0


def test_ephemeral_source_embeds_adapter() -> None:
    cfg = build_probe_config(adapter="gleam", max_pages=2, max_depth=1)
    source = ephemeral_source("https://gleam.io/x/", cfg)
    assert source.id is not None
    assert source.crawl_config["adapter"] == "gleam"
    assert source.crawl_config["max_pages"] == 2
    assert source.name.startswith("probe:")
