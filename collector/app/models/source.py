"""Crawl source domain model."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class SourceType(StrEnum):
    GIVEAWAY_AGGREGATOR = "giveaway_aggregator"
    BRAND = "brand"
    BLOG = "blog"
    FORUM = "forum"
    OTHER = "other"


class Source(BaseModel):
    """A website or feed to crawl for giveaways."""

    id: UUID | None = None
    name: str
    base_url: HttpUrl
    source_type: SourceType = SourceType.OTHER
    enabled: bool = True
    crawl_interval_minutes: int = Field(default=60, ge=5)
    last_crawled_at: datetime | None = None
    next_crawl_at: datetime | None = None
    crawl_config: dict[str, Any] = Field(default_factory=dict)
    consecutive_failures: int = 0
    last_error_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
