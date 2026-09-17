"""Conservative limits for first real-source crawl experiments."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.scraping.spider import SpiderLimits

# Hard caps for `crawl --real-test` (intentional, not production defaults).
# Depth 2 is required for Gleam directory: listing → /giveaways/<id> → classic.
REAL_TEST_MAX_PAGES = 10
REAL_TEST_MAX_DEPTH = 2
REAL_TEST_CONCURRENT_REQUESTS = 2
REAL_TEST_CONCURRENT_REQUESTS_PER_DOMAIN = 1


@dataclass(frozen=True, slots=True)
class RealTestOverrides:
    max_pages: int = REAL_TEST_MAX_PAGES
    max_depth: int = REAL_TEST_MAX_DEPTH
    concurrent_requests: int = REAL_TEST_CONCURRENT_REQUESTS
    concurrent_requests_per_domain: int = REAL_TEST_CONCURRENT_REQUESTS_PER_DOMAIN


def is_real_profile(crawl_config: dict | None) -> bool:
    cfg = crawl_config or {}
    return str(cfg.get("profile") or "").strip().lower() == "real"


def apply_real_test_limits(limits: SpiderLimits, _settings: Settings) -> SpiderLimits:
    """Clamp spider limits for the first live experiment."""
    return SpiderLimits(
        max_depth=min(limits.max_depth, REAL_TEST_MAX_DEPTH),
        max_pages=min(limits.max_pages, REAL_TEST_MAX_PAGES),
        candidate_threshold=limits.candidate_threshold,
        excerpt_max_chars=limits.excerpt_max_chars,
        request_timeout=limits.request_timeout,
        retries=limits.retries,
        gleam_directory_max_pages=limits.gleam_directory_max_pages,
    )
