"""Structured Gemini analysis schema (JSON only, no prose)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.extraction.france_eligibility import FranceEligibility


class EntryMethod(StrEnum):
    WEB_FORM = "web_form"
    SOCIAL = "social"
    EMAIL = "email"
    PURCHASE = "purchase"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class PrizeCategory(StrEnum):
    PHYSICAL_GOOD = "physical_good"
    CASH = "cash"
    GENERAL_GIFT_CARD = "general_gift_card"
    RESTRICTED_GIFT_CARD = "restricted_gift_card"
    DIGITAL_GAME = "digital_game"
    DIGITAL_GOOD = "digital_good"
    EXPERIENCE = "experience"
    TRAVEL = "travel"
    EVENT_TICKET = "event_ticket"
    SERVICE = "service"
    BOOKS_MEDIA = "books_media"
    DISCOUNT = "discount"
    SUBSCRIPTION = "subscription"
    OTHER = "other"
    UNKNOWN = "unknown"


_PRIZE_PREF_FIELDS = """
Does this prize give the user a useful asset or direct economic value
without requiring them to attend an event, travel somewhere, consume a
service, or spend significant additional money?
Ignore advertised marketing value alone (e.g. wedding package worth €18,000
is still unwanted). Prefer cash, prepaid money, electronics, appliances,
furniture, tools, game keys, and broadly usable gift cards.
Mark travel, hotels, flights, concert/festival/sports/cinema tickets,
escape rooms, restaurants, spa, experiences, wedding packages, coaching,
courses, books/ebook bundles, coupons, and min-spend vouchers as unwanted
with very low prize_priority (0-9).
If a giveaway includes both a desirable asset AND travel/experience
(e.g. PS5 + trip), set wanted_prize=true based on the desirable asset.
"""


class GiveawayAnalysis(BaseModel):
    """Facts extracted from a candidate page — Gemini must fill this schema."""

    is_giveaway: bool = Field(
        description="True only if the page itself is an actionable giveaway/contest entry page."
    )
    title: str | None = Field(default=None, description="Giveaway title if explicitly present.")
    summary: str | None = Field(
        default=None,
        description="Short factual summary from the page text only; null if unsure.",
    )
    prize: str | None = None
    estimated_prize_value_eur: float | None = Field(
        default=None,
        description="Estimated total prize value in EUR only if stated or clearly computable; else null.",
    )
    prize_category: PrizeCategory = Field(
        default=PrizeCategory.UNKNOWN,
        description="Primary prize taxonomy for preference filtering.",
    )
    wanted_prize: bool | None = Field(
        default=None,
        description=(
            "True if the prize is a useful asset or direct economic value; "
            "false for travel/experiences/tickets/services/books/discounts; "
            "null if unclear. " + _PRIZE_PREF_FIELDS
        ),
    )
    prize_priority: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description=(
            "0-100 desirability: 90-100 cash/prepaid/high electronics; "
            "70-89 useful goods/games; 50-69 lower-value goods; "
            "10-49 questionable; 0-9 travel/experiences/tickets/books/discounts."
        ),
    )
    preference_reason: str | None = Field(
        default=None,
        description="Short factual reason for wanted_prize / prize_category.",
    )
    requires_travel: bool | None = Field(
        default=None,
        description="True if claiming/using the prize requires travelling to a place.",
    )
    requires_additional_spend: bool | None = Field(
        default=None,
        description="True if vouchers/discounts require meaningful extra spending.",
    )
    free_entry: bool | None = None
    eligible_france: bool | None = Field(
        default=None,
        description=(
            "Compat bool: true/false only if France eligibility is explicit; else null. "
            "Prefer france_eligibility."
        ),
    )
    france_eligibility: FranceEligibility = Field(
        default=FranceEligibility.UNKNOWN,
        description=(
            "eligible | ineligible | unknown. Use unknown when not explicit; never guess."
        ),
    )
    eligibility_reason: str | None = Field(
        default=None,
        description="Short factual reason for france_eligibility from page text only.",
    )
    eligible_countries: list[str] = Field(
        default_factory=list,
        description="Country/region codes or names explicitly listed as eligible.",
    )
    excluded_countries: list[str] = Field(
        default_factory=list,
        description="Country/region codes or names explicitly excluded.",
    )
    requires_purchase: bool | None = None
    requires_social: bool | None = None
    requires_public_social_action: bool | None = Field(
        default=None,
        description=(
            "True ONLY when every valid entry path requires a public social action "
            "(comment/tag/share/story/repost/public post/hashtag/UGC), or such an "
            "action is mandatory before any entry. False when at least one "
            "non-public path exists (visit/email/follow/subscribe/Discord/login/"
            "form). Optional bonus public actions do NOT make this true. "
            "Following alone is never public. Null if unclear."
        ),
    )
    entry_acceptable: bool | None = Field(
        default=None,
        description=(
            "True when the user can obtain at least one valid entry without any "
            "public social interaction. False only when no such non-public path "
            "exists. Null if unclear. Independent from wanted_prize and France."
        ),
    )
    entry_rejection_reason: str | None = Field(
        default=None,
        description=(
            "When entry_acceptable=false because no non-public entry path exists, "
            "use: 'requires public social-media action'. Else null."
        ),
    )
    start_date: datetime | None = None
    end_date: datetime | None = None
    terms_url: str | None = None
    entry_url: str | None = None
    entry_method: EntryMethod = EntryMethod.UNKNOWN
    confidence: float = Field(ge=0.0, le=1.0)
    rejection_reason: str | None = Field(
        default=None,
        description="Required when is_giveaway is false; otherwise null.",
    )
    eligibility_notes: str | None = None
    requirements: list[str] = Field(default_factory=list)


class GiveawayBatchItemAnalysis(BaseModel):
    """One analysis row inside a micro-batch response, keyed by DB UUID."""

    giveaway_id: UUID = Field(description="Opaque database UUID supplied in the prompt; return unchanged.")
    is_giveaway: bool = Field(
        description="True only if the page itself is an actionable giveaway/contest entry page."
    )
    title: str | None = Field(default=None, description="Giveaway title if explicitly present.")
    summary: str | None = Field(
        default=None,
        description="Short factual summary from the page text only; null if unsure.",
    )
    prize: str | None = None
    estimated_prize_value_eur: float | None = Field(
        default=None,
        description="Estimated total prize value in EUR only if stated or clearly computable; else null.",
    )
    prize_category: PrizeCategory = Field(
        default=PrizeCategory.UNKNOWN,
        description="Primary prize taxonomy for preference filtering.",
    )
    wanted_prize: bool | None = Field(
        default=None,
        description=(
            "True if useful asset / economic value; false for travel/experiences/"
            "tickets/services/books/discounts; null if unclear."
        ),
    )
    prize_priority: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="0-100 desirability score for this prize.",
    )
    preference_reason: str | None = Field(
        default=None,
        description="Short factual reason for wanted_prize / prize_category.",
    )
    requires_travel: bool | None = Field(
        default=None,
        description="True if claiming/using the prize requires travelling to a place.",
    )
    requires_additional_spend: bool | None = Field(
        default=None,
        description="True if vouchers/discounts require meaningful extra spending.",
    )
    free_entry: bool | None = None
    eligible_france: bool | None = Field(
        default=None,
        description=(
            "Compat bool: true/false only if France eligibility is explicit; else null. "
            "Prefer france_eligibility."
        ),
    )
    france_eligibility: FranceEligibility = Field(
        default=FranceEligibility.UNKNOWN,
        description=(
            "eligible | ineligible | unknown. Use unknown when not explicit; never guess."
        ),
    )
    eligibility_reason: str | None = Field(
        default=None,
        description="Short factual reason for france_eligibility from page text only.",
    )
    eligible_countries: list[str] = Field(
        default_factory=list,
        description="Country/region codes or names explicitly listed as eligible.",
    )
    excluded_countries: list[str] = Field(
        default_factory=list,
        description="Country/region codes or names explicitly excluded.",
    )
    requires_purchase: bool | None = None
    requires_social: bool | None = None
    requires_public_social_action: bool | None = Field(
        default=None,
        description=(
            "True ONLY when no non-public entry path exists (public action required). "
            "False when visit/email/follow/etc. can complete entry. Follow-only is false."
        ),
    )
    entry_acceptable: bool | None = Field(
        default=None,
        description=(
            "True if at least one valid entry needs no public social action; "
            "false only when every path requires public social; null if unclear."
        ),
    )
    entry_rejection_reason: str | None = Field(
        default=None,
        description="Use 'requires public social-media action' when rejecting for required public social.",
    )
    start_date: datetime | None = None
    end_date: datetime | None = None
    terms_url: str | None = None
    entry_url: str | None = None
    entry_method: EntryMethod = EntryMethod.UNKNOWN
    confidence: float = Field(ge=0.0, le=1.0)
    rejection_reason: str | None = Field(
        default=None,
        description="Required when is_giveaway is false; otherwise null.",
    )
    eligibility_notes: str | None = None
    requirements: list[str] = Field(default_factory=list)

    def as_analysis(self) -> GiveawayAnalysis:
        """Drop giveaway_id for reuse of single-item persistence helpers."""
        return GiveawayAnalysis.model_validate(self.model_dump(exclude={"giveaway_id"}))


class GiveawayBatchAnalysis(BaseModel):
    """Structured micro-batch response: one item per supplied giveaway_id."""

    items: list[GiveawayBatchItemAnalysis] = Field(
        description="Exactly one analysis object per input giveaway_id."
    )
