"""Crawl run domain model."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class CrawlRunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class CrawlRun(BaseModel):
    """One crawler execution (per source or global)."""

    id: UUID | None = None
    source_id: UUID | None = None
    started_at: datetime
    finished_at: datetime | None = None
    status: CrawlRunStatus = CrawlRunStatus.RUNNING
    pages_fetched: int = Field(default=0, ge=0)
    candidates_found: int = Field(default=0, ge=0)
    giveaways_created: int = Field(default=0, ge=0)
    giveaways_updated: int = Field(default=0, ge=0)
    errors_count: int = Field(default=0, ge=0)
    error_summary: str | None = None
    created_at: datetime | None = None
