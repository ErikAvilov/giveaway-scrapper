"""Unit tests for deterministic prize preference heuristics."""

from __future__ import annotations

import pytest

from app.extraction.prize_preference import PrizeCategory, assess_prize_preference


@pytest.mark.parametrize(
    ("prize", "wanted", "category", "min_priority"),
    [
        ("PlayStation 5", True, PrizeCategory.PHYSICAL_GOOD, 90),
        ("KitchenAid mixer", True, PrizeCategory.PHYSICAL_GOOD, 70),
        ("Canapé 3 places / furniture sofa", True, PrizeCategory.PHYSICAL_GOOD, 70),
        ("€500 cash", True, PrizeCategory.CASH, 90),
        ("Steam game key", True, PrizeCategory.DIGITAL_GAME, 70),
        ("€100 prepaid Mastercard", True, PrizeCategory.GENERAL_GIFT_CARD, 90),
        ("€100 PayPal credit", True, PrizeCategory.CASH, 90),
    ],
)
def test_wanted_prizes(
    prize: str,
    wanted: bool,
    category: PrizeCategory,
    min_priority: int,
) -> None:
    pref = assess_prize_preference(prize=prize)
    assert pref.wanted_prize is wanted
    assert pref.prize_category == category
    assert pref.prize_priority is not None
    assert pref.prize_priority >= min_priority


@pytest.mark.parametrize(
    ("prize", "category"),
    [
        ("Trip to London worth €2,000", PrizeCategory.TRAVEL),
        ("2 tickets to a concert", PrizeCategory.EVENT_TICKET),
        ("Escape game in Paris", PrizeCategory.EXPERIENCE),
        ("Wedding package worth €18,000", PrizeCategory.SERVICE),
        ("Bundle of 20 books", PrizeCategory.BOOKS_MEDIA),
    ],
)
def test_unwanted_prizes(prize: str, category: PrizeCategory) -> None:
    pref = assess_prize_preference(prize=prize)
    assert pref.wanted_prize is False
    assert pref.prize_category == category
    assert pref.prize_priority is not None
    assert pref.prize_priority <= 9


def test_restricted_voucher_requires_additional_spend() -> None:
    pref = assess_prize_preference(
        prize="€50 voucher valid on purchases over €300",
    )
    assert pref.wanted_prize is False
    assert pref.prize_category == PrizeCategory.RESTRICTED_GIFT_CARD
    assert pref.requires_additional_spend is True
    assert pref.prize_priority is not None
    assert pref.prize_priority <= 9


def test_ps5_plus_trip_stays_wanted() -> None:
    pref = assess_prize_preference(prize="Win a PS5 + trip to Japan")
    assert pref.wanted_prize is True
    assert pref.prize_category == PrizeCategory.PHYSICAL_GOOD
    assert pref.prize_priority is not None
    assert pref.prize_priority >= 90
    assert pref.requires_travel is True


def test_wedding_high_value_still_unwanted() -> None:
    pref = assess_prize_preference(
        title="Win a luxury wedding package",
        prize="Wedding package worth €18,000",
    )
    assert pref.wanted_prize is False
    assert pref.prize_priority is not None
    assert pref.prize_priority <= 5


def test_french_unwanted_terms() -> None:
    pref = assess_prize_preference(prize="Week-end hôtel à Londres + billet concert")
    assert pref.wanted_prize is False
    assert pref.prize_priority is not None
    assert pref.prize_priority <= 9
