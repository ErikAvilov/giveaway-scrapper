"""Deterministic prize preference / economic-value heuristics (pre-Gemini)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from app.extraction.entry_assessment import normalize_text


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


@dataclass(slots=True, frozen=True)
class PrizePreference:
    """Conservative local classification of prize desirability."""

    prize_category: PrizeCategory
    wanted_prize: bool | None
    prize_priority: int | None  # 0-100; None when unknown
    preference_reason: str | None
    requires_travel: bool | None
    requires_additional_spend: bool | None


# --- Wanted asset signals (standalone economic value) ---

_WANTED_CASH: tuple[tuple[str, str], ...] = (
    (r"\b(?:€|eur|euros?)\s*\d", "cash_amount"),
    (r"\b\d[\d\s.,]*\s*(?:€|eur|euros?)\b", "cash_amount"),
    (r"\b(?:cash|argent|virement|bank\s+transfer)\b", "cash"),
    (r"\bpaypal\b", "paypal"),
    (r"\bprepaid\s+(?:visa|mastercard|card)\b", "prepaid_card"),
    (r"\bcarte\s+prepayee\s+(?:visa|mastercard)\b", "prepaid_card"),
    (r"\bvisa\s+prepaid\b", "prepaid_card"),
    (r"\bmastercard\s+prepaid\b", "prepaid_card"),
)

_WANTED_PHYSICAL: tuple[tuple[str, str], ...] = (
    (r"\bps\s*5\b|\bplaystation\s*5\b|\bplaystation\b|\bxbox\s*series|\bnintendo\s+switch", "console"),
    (r"\bgaming\s+(?:pc|laptop|rig|monitor|chair|headset|keyboard|mouse)\b", "gaming_hw"),
    (r"\b(?:gpu|graphics\s+card|rtx\s*\d|radeon|geforce)\b", "pc_component"),
    (r"\b(?:iphone|smartphone|galaxy\s+s\d|pixel\s+\d|ipad|tablet)\b", "phone_tablet"),
    (r"\b(?:tv|television|television|ecran\s+oled|oled\s+tv)\b", "tv"),
    (r"\b(?:headphones?|earbuds?|airpods|casque|ecouteurs)\b", "audio"),
    (r"\b(?:camera|appareil\s+photo|gopro|dslr|mirrorless)\b", "camera"),
    (r"\b(?:laptop|ordinateur|macbook|imac|pc\s+portable|computer)\b", "computer"),
    (
        (
            r"\b(?:kitchenaid|mixeur|blender|airfryer|air\s+fryer|robot\s+cuisine|four|frigo|"
            r"refrigerateur|lave[- ]?vaisselle|lave[- ]?linge|aspirateur|dyson|electromenager)\b"
        ),
        "appliance",
    ),
    (r"\b(?:furniture|meuble|canape|sofa|matelas|bureau|chaise\s+de\s+bureau)\b", "furniture"),
    (r"\b(?:velo|bicycle|bike|trottinette|scooter|e[- ]?bike)\b", "mobility"),
    (r"\b(?:outil|tools?|perceuse|drill|scie)\b", "tools"),
    (r"\belectroni", "electronics"),
)

_WANTED_DIGITAL: tuple[tuple[str, str], ...] = (
    (r"\bsteam\b", "steam"),
    (r"\b(?:psn|playstation)\s+(?:store\s+)?(?:code|card|key|credit)\b", "console_digital"),
    (r"\bxbox\s+(?:live\s+)?(?:gift\s+)?(?:card|code|key|credit)\b", "console_digital"),
    (r"\bnintendo\s+(?:eshop|e[- ]?shop|gift)\b", "console_digital"),
    (r"\b(?:game\s+key|steam\s+key|cd\s*key|cle\s+(?:steam|jeu))\b", "game_key"),
    (r"\b(?:video\s+)?game\s+(?:code|key|download)\b", "game_key"),
    (r"\blicen[cs]e\s+(?:logiciel|software)\b", "software"),
    (r"\b(?:adobe|microsoft\s+365|office\s+365)\s+(?:licence|license|subscription)?\b", "software"),
)

_WANTED_GIFT_BROAD: tuple[tuple[str, str], ...] = (
    (r"\bamazon\s+(?:gift\s+)?card\b|\bcarte\s+(?:cadeau\s+)?amazon\b", "amazon_gc"),
    (r"\bcarte\s+cadeau\b|\bgift\s+card\b", "gift_card"),
)

# --- Unwanted: experiences, travel, tickets, books, discounts ---

_UNWANTED_TRAVEL: tuple[tuple[str, str], ...] = (
    (r"\b(?:voyage|trip|holiday|vacation|sejour|week[- ]?end)\b", "travel"),
    (r"\b(?:hotel|hôtel|flight|vol\s+(?:aller|pour)|billets?\s+d[' ]avion)\b", "travel"),
    (r"\b(?:travel\s+package|forfait\s+voyage|city\s+break)\b", "travel"),
)

_UNWANTED_TICKETS: tuple[tuple[str, str], ...] = (
    (r"\b(?:concert|festival|billet|ticket)s?\b", "event_ticket"),
    (r"\b(?:cinema|cinéma|match|stadium|stade)\b", "event_ticket"),
    (r"\b(?:sports?\s+tickets?|event\s+tickets?)\b", "event_ticket"),
)

_UNWANTED_EXPERIENCE: tuple[tuple[str, str], ...] = (
    (r"\b(?:escape\s*(?:game|room)|escape[- ]game)\b", "experience"),
    (r"\b(?:restaurant|repas|diner|dîner|meal|dinner)\b", "experience"),
    (r"\b(?:spa|wellness|massage)\b", "experience"),
    (r"\b(?:experience|expérience|activite|activité)\b", "experience"),
    (r"\b(?:mariage|wedding\s+package|wedding)\b", "wedding"),
    (r"\b(?:shooting|photoshoot|seance\s+photo|séance\s+photo|photography\s+session)\b", "service"),
    (r"\b(?:coaching|formation|course|cours\b|workshop)\b", "service"),
)

_UNWANTED_BOOKS: tuple[tuple[str, str], ...] = (
    (r"\b(?:livres?|books?|ebooks?|ebook\s+bundle|bundle\s+de\s+livres|book\s+bundle)\b", "books"),
    (r"\b(?:magazine|abonnement\s+(?:magazine|presse)|magazine\s+subscription)\b", "subscription"),
)

_UNWANTED_DISCOUNT: tuple[tuple[str, str], ...] = (
    (r"\b(?:reduction|réduction|remise|discount|coupon|%\s*off|pourcent)\b", "discount"),
    (r"\b(?:bon\s+d[' ]achat\s+des|offerts?\s+des|voucher\s+(?:valid\s+)?(?:on|for)\s+purchases?\s+over)\b", "min_spend"),
    (r"\b(?:€|eur)?\s*\d+\s*(?:€|eur)?\s*(?:off|de\s+reduction|de\s+réduction).{0,40}(?:over|d[eè]s|à\s+partir|achat|spend|purchases?)\b", "min_spend"),
    (r"\b(?:purchases?\s+over|minimum\s+spend|spend\s+(?:of\s+)?(?:€|\$|eur)?\s*\d+)\b", "min_spend"),
    (r"\b(?:d[eè]s\s+\d+|à\s+partir\s+de\s+\d+).{0,20}(?:€|eur)\b", "min_spend"),
)


def _hits(blob: str, patterns: tuple[tuple[str, str], ...]) -> list[str]:
    found: list[str] = []
    for pattern, label in patterns:
        if re.search(pattern, blob, re.IGNORECASE):
            found.append(label)
    return found


def _unique(labels: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for label in labels:
        if label not in seen:
            seen.add(label)
            out.append(label)
    return out


def assess_prize_preference(
    *,
    title: str | None = None,
    prize: str | None = None,
    body: str | None = None,
) -> PrizePreference:
    """
    Conservative local prize preference from title/prize/text.

    Does NOT hard-reject multi-prize giveaways that include a desirable asset
    alongside travel/experiences (e.g. "PS5 + trip to Tokyo" stays wanted).
    """
    blob = normalize_text(" ".join(p for p in (title, prize, body) if p))
    if not blob.strip():
        return PrizePreference(
            prize_category=PrizeCategory.UNKNOWN,
            wanted_prize=None,
            prize_priority=None,
            preference_reason="insufficient_prize_text",
            requires_travel=None,
            requires_additional_spend=None,
        )

    cash = _hits(blob, _WANTED_CASH)
    physical = _hits(blob, _WANTED_PHYSICAL)
    digital = _hits(blob, _WANTED_DIGITAL)
    gift_broad = _hits(blob, _WANTED_GIFT_BROAD)

    travel = _hits(blob, _UNWANTED_TRAVEL)
    tickets = _hits(blob, _UNWANTED_TICKETS)
    experience = _hits(blob, _UNWANTED_EXPERIENCE)
    books = _hits(blob, _UNWANTED_BOOKS)
    discount = _hits(blob, _UNWANTED_DISCOUNT)

    has_min_spend = "min_spend" in discount
    # Bare "€50" in a voucher/discount context is not cash.
    explicit_cash = [c for c in cash if c != "cash_amount"]
    if has_min_spend or discount:
        cash = explicit_cash
    elif "cash_amount" in cash and not explicit_cash and (
        travel or tickets or experience or books
    ):
        # Amount alone is weak when the prize is clearly an experience/travel/etc.
        cash = []

    has_wanted_asset = bool(cash or physical or digital)
    if "amazon_gc" in gift_broad and not has_min_spend:
        has_wanted_asset = True
    # Prepaid / PayPal already counted in cash; keep gift_card alone as uncertain later.

    unwanted_labels = _unique([*travel, *tickets, *experience, *books, *discount])
    has_unwanted = bool(unwanted_labels)

    # --- Multi-prize: desirable asset wins ---
    if has_wanted_asset:
        category, priority, reason = _classify_wanted(
            cash=cash,
            physical=physical,
            digital=digital,
            gift_broad=gift_broad,
            also_unwanted=has_unwanted,
        )
        return PrizePreference(
            prize_category=category,
            wanted_prize=True,
            prize_priority=priority,
            preference_reason=reason,
            requires_travel=bool(travel),
            requires_additional_spend=bool(has_min_spend),
        )

    # Restricted / min-spend vouchers
    if has_min_spend or (gift_broad and ("discount" in discount or has_min_spend)):
        return PrizePreference(
            prize_category=PrizeCategory.RESTRICTED_GIFT_CARD,
            wanted_prize=False,
            prize_priority=3,
            preference_reason="restricted_voucher_additional_spend:"
            + ",".join(unwanted_labels[:4] or gift_broad[:2]),
            requires_travel=bool(travel),
            requires_additional_spend=True,
        )

    if discount and not gift_broad:
        return PrizePreference(
            prize_category=PrizeCategory.DISCOUNT,
            wanted_prize=False,
            prize_priority=2,
            preference_reason="discount_coupon:" + ",".join(discount),
            requires_travel=False,
            requires_additional_spend=True,
        )

    if gift_broad and discount:
        return PrizePreference(
            prize_category=PrizeCategory.RESTRICTED_GIFT_CARD,
            wanted_prize=False,
            prize_priority=5,
            preference_reason="restricted_gift_card:" + ",".join(unwanted_labels[:4]),
            requires_travel=False,
            requires_additional_spend=True,
        )

    if travel and not tickets and not experience:
        return PrizePreference(
            prize_category=PrizeCategory.TRAVEL,
            wanted_prize=False,
            prize_priority=2,
            preference_reason="travel:" + ",".join(travel),
            requires_travel=True,
            requires_additional_spend=False,
        )

    if tickets:
        return PrizePreference(
            prize_category=PrizeCategory.EVENT_TICKET,
            wanted_prize=False,
            prize_priority=2,
            preference_reason="event_ticket:" + ",".join(tickets),
            requires_travel=bool(travel),
            requires_additional_spend=False,
        )

    if "wedding" in experience:
        return PrizePreference(
            prize_category=PrizeCategory.SERVICE,
            wanted_prize=False,
            prize_priority=1,
            preference_reason="wedding_or_service:" + ",".join(experience),
            requires_travel=True,
            requires_additional_spend=False,
        )

    if experience:
        cat = (
            PrizeCategory.SERVICE
            if "service" in experience
            else PrizeCategory.EXPERIENCE
        )
        return PrizePreference(
            prize_category=cat,
            wanted_prize=False,
            prize_priority=3,
            preference_reason="experience:" + ",".join(experience),
            requires_travel=bool(travel) or cat == PrizeCategory.EXPERIENCE,
            requires_additional_spend=False,
        )

    if books:
        cat = (
            PrizeCategory.SUBSCRIPTION
            if "subscription" in books
            else PrizeCategory.BOOKS_MEDIA
        )
        return PrizePreference(
            prize_category=cat,
            wanted_prize=False,
            prize_priority=4,
            preference_reason="books_media:" + ",".join(books),
            requires_travel=False,
            requires_additional_spend=False,
        )

    # Generic gift card alone — uncertain until Gemini
    if gift_broad:
        return PrizePreference(
            prize_category=PrizeCategory.GENERAL_GIFT_CARD,
            wanted_prize=None,
            prize_priority=55,
            preference_reason="gift_card_unverified:" + ",".join(gift_broad),
            requires_travel=False,
            requires_additional_spend=None,
        )

    # Bare cash amount without other signals → treat as likely cash
    if "cash_amount" in _hits(blob, _WANTED_CASH):
        return PrizePreference(
            prize_category=PrizeCategory.CASH,
            wanted_prize=True,
            prize_priority=90,
            preference_reason="cash_amount",
            requires_travel=False,
            requires_additional_spend=False,
        )

    return PrizePreference(
        prize_category=PrizeCategory.UNKNOWN,
        wanted_prize=None,
        prize_priority=50,
        preference_reason="unknown_prize",
        requires_travel=None,
        requires_additional_spend=None,
    )

def _classify_wanted(
    *,
    cash: list[str],
    physical: list[str],
    digital: list[str],
    gift_broad: list[str],
    also_unwanted: bool,
) -> tuple[PrizeCategory, int, str]:
    suffix = "+mixed_unwanted" if also_unwanted else ""
    if cash:
        if any(x in cash for x in ("prepaid_card", "paypal")):
            return (
                PrizeCategory.GENERAL_GIFT_CARD
                if "prepaid_card" in cash
                else PrizeCategory.CASH,
                95,
                "cash_or_prepaid:" + ",".join(cash) + suffix,
            )
        return PrizeCategory.CASH, 98, "cash:" + ",".join(cash) + suffix
    if physical:
        high = {"console", "gaming_hw", "pc_component", "phone_tablet", "computer", "tv"}
        mid = {"appliance", "furniture", "tools", "mobility", "camera", "audio", "electronics"}
        labels = set(physical)
        if labels & high:
            return PrizeCategory.PHYSICAL_GOOD, 92, "physical_high:" + ",".join(physical) + suffix
        if labels & mid:
            return PrizeCategory.PHYSICAL_GOOD, 78, "physical_useful:" + ",".join(physical) + suffix
        return PrizeCategory.PHYSICAL_GOOD, 72, "physical:" + ",".join(physical) + suffix
    if digital:
        if any(x in digital for x in ("steam", "game_key", "console_digital")):
            return PrizeCategory.DIGITAL_GAME, 75, "digital_game:" + ",".join(digital) + suffix
        return PrizeCategory.DIGITAL_GOOD, 70, "digital_good:" + ",".join(digital) + suffix
    if "amazon_gc" in gift_broad:
        return (
            PrizeCategory.GENERAL_GIFT_CARD,
            80,
            "marketplace_gift_card:" + ",".join(gift_broad) + suffix,
        )
    return (
        PrizeCategory.GENERAL_GIFT_CARD,
        65,
        "gift_card:" + ",".join(gift_broad) + suffix,
    )


def analysis_queue_rank(pref: PrizePreference | None) -> int:
    """
    Sort key for Gemini pending queue (lower = analyze sooner).

    1. likely wanted / cash / physical / gaming
    2. unknown
    3. likely experiences / services
    4. obvious unwanted
    """
    if pref is None or pref.wanted_prize is None:
        return 100
    if pref.wanted_prize is True:
        priority = pref.prize_priority if pref.prize_priority is not None else 50
        return 50 - min(priority, 100)  # high priority → lower rank
    # unwanted
    priority = pref.prize_priority if pref.prize_priority is not None else 0
    if pref.prize_category in {
        PrizeCategory.TRAVEL,
        PrizeCategory.EVENT_TICKET,
        PrizeCategory.EXPERIENCE,
        PrizeCategory.SERVICE,
        PrizeCategory.BOOKS_MEDIA,
        PrizeCategory.DISCOUNT,
        PrizeCategory.RESTRICTED_GIFT_CARD,
        PrizeCategory.SUBSCRIPTION,
    }:
        return 300 + (10 - min(priority, 10))
    return 200
