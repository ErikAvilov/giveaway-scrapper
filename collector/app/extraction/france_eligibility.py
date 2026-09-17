"""France eligibility classification (hard gate for France-first profile)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from app.extraction.entry_assessment import GeoScope, infer_geo_scope


class FranceEligibility(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    UNKNOWN = "unknown"


@dataclass(slots=True, frozen=True)
class FranceEligibilityResult:
    france_eligibility: FranceEligibility
    eligible_france: bool | None
    reason: str | None
    eligible_countries: tuple[str, ...] = ()
    excluded_countries: tuple[str, ...] = ()

    @property
    def skip_gemini(self) -> bool:
        """Clear local decision — no need to spend Gemini on geo."""
        return self.france_eligibility in {
            FranceEligibility.ELIGIBLE,
            FranceEligibility.INELIGIBLE,
        } and bool(self.reason and self.reason.startswith("local_"))


_FRANCE_EXCLUDED = re.compile(
    r"\bexclud(?:e|ing|es)\s+france\b|"
    r"\bnot\s+(?:open|available)\s+(?:in|to)\s+france\b|"
    r"\bexcept\s+france\b|"
    r"\bhors\s+france\b",
    re.IGNORECASE,
)
_FRANCE_POSITIVE = re.compile(
    r"\bouvert\s+[àa]\s+toute\s+personne\s+r[eé]sidant\s+en\s+france\b|"
    r"\bfrance\s+m[eé]tropolitaine\b|"
    r"\bfrance\s+only\b|"
    r"\bopen\s+to\s+(?:france|french\s+residents)\b|"
    r"\bresidents?\s+(?:of\s+)?france\b|"
    r"\belligible\s+france\b|"
    r"\bfrance\s+(?:et|/)\s*(?:belgique|dom|tom|ue|eu)\b|"
    r"\br[eé]sidents?\s+(?:en\s+)?france\b|"
    r"\bouvert\s+(?:aux?\s+)?(?:r[eé]sidents?\s+)?(?:en\s+)?france\b|"
    r"\bfrance\b",
    re.IGNORECASE,
)
_WORLDWIDE = re.compile(
    r"\bworldwide\b|\binternational\b|"
    r"\bopen\s+(?:to\s+)?(?:all\s+)?countries\b|"
    r"\banywhere\s+in\s+the\s+world\b|"
    r"\bmonde\s+entier\b|\binternationalement\b",
    re.IGNORECASE,
)
_EU = re.compile(
    r"\beu\s+(?:only|residents)\b|\beuropean\s+union\b|"
    r"\beurope\s+only\b|\beuropean\s+residents?\b|"
    r"\bunion\s+europ[eé]enne\b|\br[eé]sidents?\s+(?:de\s+)?l[' ]?ue\b|"
    r"\beu\s*/\s*eea\b|\beea\s+residents?\b",
    re.IGNORECASE,
)
_UK_ONLY = re.compile(
    r"\buk\s+residents?\s+only\b|\bunited\s+kingdom\s+only\b|"
    r"\bonly\s+(?:open\s+to\s+)?(?:uk|united\s+kingdom)\b|"
    r"\buk\s+entrants?\b|\bgb\s+residents?\s+only\b|"
    r"\bopen\s+to\s+(?:uk|united\s+kingdom)\s+residents?\b|"
    r"\bavailable\s+in\s+(?:the\s+)?united\s+kingdom\b",
    re.IGNORECASE,
)
_US_ONLY = re.compile(
    r"\bus\s+residents?\s+only\b|\bunited\s+states\s+only\b|"
    r"\busa\s+only\b|\b50\s+united\s+states\b|"
    r"\blegal\s+residents?\s+of\s+the\s+(?:fifty\s+)?(?:50\s+)?united\s+states\b|"
    r"\bonly\s+(?:open\s+to\s+)?(?:us|u\.s\.|usa|united\s+states)\b|"
    r"\bopen\s+to\s+(?:legal\s+)?residents?\s+of\s+the\s+united\s+states\b|"
    r"\bavailable\s+in\s+united\s+states\b|"
    r"\beligible\s*🇺🇸?\s*us\b|"
    r"\beligible[:\s]+(?:🇺🇸\s*)?(?:us|usa|united\s+states)\b|"
    r"(?:^|\n)🇺🇸\s*us(?:\n|$)|"
    r"^us$",
    re.IGNORECASE,
)
_CANADA_ONLY = re.compile(
    r"\bcanada\s+only\b|\bcanadian\s+residents?\s+only\b|"
    r"\bonly\s+(?:open\s+to\s+)?(?:canada|canadian)\b|"
    r"\bavailable\s+in\s+canada\b",
    re.IGNORECASE,
)
_AUSTRALIA_ONLY = re.compile(
    r"\baustralia\s+only\b|\baustralian\s+residents?\s+only\b|"
    r"\bonly\s+(?:open\s+to\s+)?(?:australia|australian)\b|"
    r"\bau\s+residents?\s+only\b",
    re.IGNORECASE,
)
_SHIPPING_RESTRICT = re.compile(
    r"\bships?\s+only\s+to\b|\bshipping\s+(?:limited|restricted)\s+to\b|"
    r"\bdeliver(?:y|ies)?\s+only\s+(?:to|within)\b",
    re.IGNORECASE,
)


def eligible_france_bool(state: FranceEligibility) -> bool | None:
    if state == FranceEligibility.ELIGIBLE:
        return True
    if state == FranceEligibility.INELIGIBLE:
        return False
    return None


def classify_france_eligibility(
    *,
    title: str | None = None,
    prize: str | None = None,
    body: str | None = None,
    restriction: str | None = None,
) -> FranceEligibilityResult:
    """
    Conservative France eligibility.

    Unknown stays unknown — never invent France eligibility from English alone.
    """
    parts = [p for p in (restriction, title, prize, body) if p and str(p).strip()]
    blob = "\n".join(parts)
    if not blob.strip():
        return FranceEligibilityResult(
            france_eligibility=FranceEligibility.UNKNOWN,
            eligible_france=None,
            reason="local_insufficient_text",
        )

    if _FRANCE_EXCLUDED.search(blob):
        return FranceEligibilityResult(
            france_eligibility=FranceEligibility.INELIGIBLE,
            eligible_france=False,
            reason="local_france_excluded",
            excluded_countries=("france",),
        )

    if _US_ONLY.search(blob):
        return FranceEligibilityResult(
            france_eligibility=FranceEligibility.INELIGIBLE,
            eligible_france=False,
            reason="local_us_only",
            eligible_countries=("us",),
        )
    if _UK_ONLY.search(blob):
        return FranceEligibilityResult(
            france_eligibility=FranceEligibility.INELIGIBLE,
            eligible_france=False,
            reason="local_uk_only",
            eligible_countries=("uk",),
        )
    if _CANADA_ONLY.search(blob):
        return FranceEligibilityResult(
            france_eligibility=FranceEligibility.INELIGIBLE,
            eligible_france=False,
            reason="local_canada_only",
            eligible_countries=("canada",),
        )
    if _AUSTRALIA_ONLY.search(blob):
        return FranceEligibilityResult(
            france_eligibility=FranceEligibility.INELIGIBLE,
            eligible_france=False,
            reason="local_australia_only",
            eligible_countries=("australia",),
        )

    # Explicit France mention (positive) before worldwide heuristics.
    if _FRANCE_POSITIVE.search(blob) and not _FRANCE_EXCLUDED.search(blob):
        # Avoid matching random "france" in shipping exclusions already handled.
        # If the only hit is weak and paired with US/UK-only patterns — already returned.
        return FranceEligibilityResult(
            france_eligibility=FranceEligibility.ELIGIBLE,
            eligible_france=True,
            reason="local_france_explicit",
            eligible_countries=("france",),
        )

    if _WORLDWIDE.search(blob):
        return FranceEligibilityResult(
            france_eligibility=FranceEligibility.ELIGIBLE,
            eligible_france=True,
            reason="local_worldwide",
            eligible_countries=("worldwide",),
        )

    if _EU.search(blob):
        return FranceEligibilityResult(
            france_eligibility=FranceEligibility.ELIGIBLE,
            eligible_france=True,
            reason="local_eu",
            eligible_countries=("eu", "france"),
        )

    # Restriction-only scope via existing helper.
    scope = infer_geo_scope(restriction) if restriction else GeoScope.UNKNOWN
    if scope == GeoScope.WORLDWIDE:
        return FranceEligibilityResult(
            FranceEligibility.ELIGIBLE, True, "local_scope_worldwide", ("worldwide",)
        )
    if scope in {GeoScope.FRANCE, GeoScope.EU}:
        return FranceEligibilityResult(
            FranceEligibility.ELIGIBLE, True, f"local_scope_{scope.value}", (scope.value,)
        )
    if scope in {GeoScope.UK, GeoScope.US, GeoScope.CANADA}:
        return FranceEligibilityResult(
            FranceEligibility.INELIGIBLE,
            False,
            f"local_scope_{scope.value}",
            (scope.value,),
        )

    if scope == GeoScope.SPECIFIC:
        text = restriction or ""
        if _FRANCE_POSITIVE.search(text) and not _FRANCE_EXCLUDED.search(text):
            return FranceEligibilityResult(
                FranceEligibility.ELIGIBLE, True, "local_specific_includes_france", ("france",)
            )
        if re.search(r"\bonly\b", text, re.IGNORECASE):
            return FranceEligibilityResult(
                FranceEligibility.INELIGIBLE,
                False,
                "local_specific_only_without_france",
            )

    if _SHIPPING_RESTRICT.search(blob):
        # Shipping-limited without France mention → unknown (do not auto-reject).
        return FranceEligibilityResult(
            FranceEligibility.UNKNOWN, None, "local_shipping_restricted_ambiguous"
        )

    # No positive France evidence.
    return FranceEligibilityResult(
        france_eligibility=FranceEligibility.UNKNOWN,
        eligible_france=None,
        reason="local_unknown",
    )


def sync_eligible_france_column(state: FranceEligibility | str | None) -> bool | None:
    if state is None:
        return None
    try:
        return eligible_france_bool(FranceEligibility(str(state)))
    except ValueError:
        return None
