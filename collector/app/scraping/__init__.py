"""HTTP crawling and giveaway candidate discovery via Scrapling."""

from app.scraping.filters import should_follow_url
from app.scraping.runner import crawl_all, crawl_source
from app.scraping.scoring import score_candidate
from app.scraping.seed import seed_sources

__all__ = [
    "crawl_all",
    "crawl_source",
    "score_candidate",
    "seed_sources",
    "should_follow_url",
]
