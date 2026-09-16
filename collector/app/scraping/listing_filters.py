"""Source-level listing filters (geo + prize category) before detail fetches."""

from __future__ import annotations

import re
from collections.abc import Iterable

# Categories we prioritize on aggregators (substring match, case-insensitive).
WANTED_CATEGORY_HINTS: tuple[str, ...] = (
    "electronics",
    "gadget",
    "gaming",
    "game",
    "console",
    "pc",
    "computer",
    "technology",
    "tech",
    "smartphone",
    "tablet",
    "home",
    "furniture",
    "appliance",
    "kitchen",
    "tools",
    "hardware",
    "cash",
    "paypal",
    "gift card",
    "giftcard",
    "prepaid",
    "visa",
    "mastercard",
    "steam",
    "playstation",
    "xbox",
    "nintendo",
)

UNWANTED_CATEGORY_HINTS: tuple[str, ...] = (
    "travel",
    "hotel",
    "flight",
    "vacation",
    "holiday",
    "concert",
    "ticket",
    "experience",
    "escape",
    "restaurant",
    "wedding",
    "crypto",
    "nft",
    "course",
    "book",
)

_WORLDWIDE_RE = re.compile(
    r"\bworldwide\b|\binternational\b|\bopen\s+worldwide\b|\bmonde\s+entier\b",
    re.IGNORECASE,
)
_US_BADGE_RE = re.compile(
    r"\b(?:🇺🇸\s*)?(?:us|usa|united\s+states)\b(?!\s*/)",
    re.IGNORECASE,
)
_UK_BADGE_RE = re.compile(r"\b(?:🇬🇧\s*)?(?:uk|united\s+kingdom)\b", re.IGNORECASE)


def normalize_blob(*parts: str | None) -> str:
    return " ".join(p.strip() for p in parts if p and str(p).strip())


def is_worldwide_text(text: str | None) -> bool:
    return bool(text and _WORLDWIDE_RE.search(text))


def is_us_only_badge(text: str | None) -> bool:
    if not text or is_worldwide_text(text):
        return False
    return bool(_US_BADGE_RE.search(text)) and not is_worldwide_text(text)


def is_uk_only_badge(text: str | None) -> bool:
    if not text or is_worldwide_text(text):
        return False
    return bool(_UK_BADGE_RE.search(text)) and "uk/" not in (text or "").lower()


def category_is_wanted(text: str | None) -> bool | None:
    """
    True = wanted hint, False = unwanted hint, None = unknown/neutral.
    Unwanted wins if both match.
    """
    if not text:
        return None
    low = text.lower()
    unwanted = any(h in low for h in UNWANTED_CATEGORY_HINTS)
    wanted = any(h in low for h in WANTED_CATEGORY_HINTS)
    if unwanted:
        return False
    if wanted:
        return True
    return None


def prefer_listing_card(
    *,
    geo_text: str | None,
    category_text: str | None,
    title: str | None = None,
    require_worldwide: bool = True,
) -> bool:
    """
    Return True when a listing card is worth fetching/keeping for France-first.

    When require_worldwide is True, non-worldwide geo is rejected.
    Unknown geo is kept only when require_worldwide is False.
    """
    if require_worldwide:
        if geo_text and (is_us_only_badge(geo_text) or is_uk_only_badge(geo_text)):
            return False
        if geo_text and not is_worldwide_text(geo_text):
            if re.search(
                r"\b(?:canada|australia|india|germany|brazil)\b",
                geo_text,
                re.IGNORECASE,
            ):
                return False
            if re.search(r"[A-Za-z]{2,}", geo_text):
                return False
        if not geo_text or not is_worldwide_text(geo_text):
            return False

    cat = category_is_wanted(normalize_blob(category_text, title))
    return cat is not False


def any_wanted_hint(texts: Iterable[str | None]) -> bool:
    return any(category_is_wanted(t) is True for t in texts)
