"""Giveaway domain model."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class GiveawayStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    EXPIRED = "expired"
    REJECTED = "rejected"
    UNCERTAIN = "uncertain"


class ManualStatus(StrEnum):
    NONE = "none"
    INTERESTED = "interested"
    ENTERED = "entered"
    IGNORED = "ignored"
    WON = "won"
    LOST = "lost"


class Giveaway(BaseModel):
    """A discovered giveaway (unique on canonical_url)."""

    id: UUID | None = None
    canonical_url: HttpUrl | str
    original_url: HttpUrl | str
    source_id: UUID | None = None
    domain: str
    title: str | None = None
    description: str | None = None
    prize: str | None = None
    prize_value_eur: Decimal | None = None
    prize_category: str | None = None
    wanted_prize: bool | None = None
    prize_priority: int | None = Field(default=None, ge=0, le=100)
    preference_reason: str | None = None
    requires_travel: bool | None = None
    requires_additional_spend: bool | None = None
    free_entry: bool | None = None
    eligible_france: bool | None = None
    france_eligibility: str | None = None
    eligibility_reason: str | None = None
    eligible_countries: list[str] = Field(default_factory=list)
    excluded_countries: list[str] = Field(default_factory=list)
    requires_purchase: bool | None = None
    requires_social: bool | None = None
    entry_method: str | None = None
    entry_friction: str | None = None
    geo_restriction: str | None = None
    platform: str | None = None
    platform_campaign_id: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    terms_url: str | None = None
    entry_url: str | None = None
    entry_http_status: int | None = None
    entry_checked_at: datetime | None = None
    entry_url_status: str | None = None
    entry_fail_count: int = 0
    status: GiveawayStatus = GiveawayStatus.CANDIDATE
    confidence: float | None = Field(default=None, ge=0, le=1)
    content_hash: str
    discovered_at: datetime | None = None
    last_seen_at: datetime | None = None
    analyzed_at: datetime | None = None
    raw_excerpt: str | None = None
    link_hints: list[str] = Field(default_factory=list)
    analysis_json: dict[str, Any] | None = None
    manual_status: ManualStatus = ManualStatus.NONE
    remind_at: datetime | None = None
    reminder_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    requires_public_social_action: bool | None = None
    entry_acceptable: bool | None = None
    entry_rejection_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
