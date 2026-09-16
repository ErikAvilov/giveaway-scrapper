"""France eligibility classification regression tests."""

from __future__ import annotations

import pytest

from app.extraction.france_eligibility import (
    FranceEligibility,
    classify_france_eligibility,
)
from app.extraction.prize_preference import assess_prize_preference
from app.gemini.schema import EntryMethod, GiveawayAnalysis
from app.gemini.service import decide_status
from app.models.giveaway import GiveawayStatus


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            {"restriction": "Ouvert aux résidents en France métropolitaine"},
            FranceEligibility.ELIGIBLE,
        ),
        ({"restriction": "Open worldwide"}, FranceEligibility.ELIGIBLE),
        ({"restriction": "Open to international participants"}, FranceEligibility.ELIGIBLE),
        ({"restriction": "EU residents only"}, FranceEligibility.ELIGIBLE),
        ({"restriction": "UK residents only"}, FranceEligibility.INELIGIBLE),
        (
            {"restriction": "Open to legal residents of the 50 United States"},
            FranceEligibility.INELIGIBLE,
        ),
        ({"restriction": "Canada only"}, FranceEligibility.INELIGIBLE),
        ({"restriction": "Australia residents only"}, FranceEligibility.INELIGIBLE),
        (
            {"restriction": "Open to residents of Germany and Spain only"},
            FranceEligibility.INELIGIBLE,
        ),
        ({"body": "Enter our sweepstakes today."}, FranceEligibility.UNKNOWN),
        ({}, FranceEligibility.UNKNOWN),
    ],
)
def test_classify_france_eligibility_cases(
    kwargs: dict[str, str],
    expected: FranceEligibility,
) -> None:
    result = classify_france_eligibility(**kwargs)
    assert result.france_eligibility == expected
    if expected == FranceEligibility.ELIGIBLE:
        assert result.eligible_france is True
    elif expected == FranceEligibility.INELIGIBLE:
        assert result.eligible_france is False
    else:
        assert result.eligible_france is None


def test_unknown_never_becomes_eligible_from_english_alone() -> None:
    result = classify_france_eligibility(
        title="Win a laptop",
        body="Fill out the form to enter this free giveaway. Official rules apply.",
    )
    assert result.france_eligibility == FranceEligibility.UNKNOWN
    assert result.eligible_france is None


def test_decide_status_france_gates() -> None:
    base = {
        "is_giveaway": True,
        "confidence": 0.9,
        "wanted_prize": True,
        "entry_method": EntryMethod.WEB_FORM,
        "entry_acceptable": True,
        "requires_public_social_action": False,
    }
    assert (
        decide_status(
            GiveawayAnalysis(
                **base,
                france_eligibility=FranceEligibility.ELIGIBLE,
                eligible_france=True,
            )
        )
        == GiveawayStatus.ACTIVE
    )
    assert (
        decide_status(
            GiveawayAnalysis(
                **base,
                france_eligibility=FranceEligibility.INELIGIBLE,
                eligible_france=False,
            )
        )
        == GiveawayStatus.REJECTED
    )
    assert (
        decide_status(
            GiveawayAnalysis(
                **base,
                france_eligibility=FranceEligibility.UNKNOWN,
                eligible_france=None,
            )
        )
        == GiveawayStatus.UNCERTAIN
    )
    unwanted = {**base, "wanted_prize": False}
    assert (
        decide_status(
            GiveawayAnalysis(
                **unwanted,
                france_eligibility=FranceEligibility.ELIGIBLE,
            )
        )
        == GiveawayStatus.REJECTED
    )
    assert (
        decide_status(
            GiveawayAnalysis(
                **base,
                france_eligibility=FranceEligibility.ELIGIBLE,
            ),
            entry_url_status="gone",
        )
        == GiveawayStatus.REJECTED
    )


def test_france_plus_ps5_wanted_us_only_rejected_trip_unwanted() -> None:
    fr = classify_france_eligibility(restriction="France métropolitaine")
    assert fr.france_eligibility == FranceEligibility.ELIGIBLE
    ps5 = assess_prize_preference(prize="PlayStation 5 console")
    assert ps5.wanted_prize is True

    us = classify_france_eligibility(
        restriction="Open to legal residents of the 50 United States",
    )
    assert us.france_eligibility == FranceEligibility.INELIGIBLE

    trip = assess_prize_preference(prize="Weekend trip to Paris hotel stay")
    assert trip.wanted_prize is False
