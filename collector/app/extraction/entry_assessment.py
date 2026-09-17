"""Deterministic entry-friction, geo eligibility, and undesirability signals."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum


def normalize_text(text: str) -> str:
    """Lowercase + strip accents for robust FR/EN matching."""
    lowered = text.lower()
    decomposed = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


class EntryFriction(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    UNKNOWN = "unknown"


class GeoScope(StrEnum):
    WORLDWIDE = "worldwide"
    EU = "eu"
    FRANCE = "france"
    UK = "uk"
    US = "us"
    CANADA = "canada"
    SPECIFIC = "specific"
    UNKNOWN = "unknown"


@dataclass(slots=True, frozen=True)
class EntryAssessment:
    entry_friction: EntryFriction
    free_entry: bool | None
    requires_purchase: bool | None
    requires_social: bool | None
    entry_method: str | None
    geo_scope: GeoScope
    geo_restriction: str | None
    eligible_france: bool | None
    skip_gemini: bool
    skip_reasons: tuple[str, ...]
    discovery_priority: int  # lower = better for our project


_HARD_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"(?<!\bno\s)\bpurchase\s+required\b(?!\s*:?\s*no\b)", "purchase_required"),
    (r"\bmust\s+purchase\b", "purchase_required"),
    (r"\bbuy\s+to\s+enter\b", "purchase_required"),
    (r"\bpaid\s+entr(?:y|ies)\b", "paid_entry"),
    (r"\bentry\s+fee\b", "paid_entry"),
    (r"\bticket\s+(?:to\s+)?enter\b", "paid_entry"),
    (r"\bpostal\s+(?:entr(?:y|ies)|only)\b", "postal_only"),
    (r"\bsend\s+(?:a\s+)?(?:sae|stamped\s+addressed\s+envelope)\b", "postal_only"),
    (r"\bmail[- ]?in\s+(?:only\s+)?entr", "postal_only"),
    # Referral / share / comment presence is NOT a hard reject — optional bonus
    # methods are evaluated by the entry-path gate instead.
    (r"\bdaily\s+entr(?:y|ies)\b", "daily_entry"),
    (r"\benter\s+(?:every|each)\s+day\b", "daily_entry"),
    (r"\bcreative\s+submission\b", "creative"),
    (r"\bsubmit\s+(?:a\s+)?(?:photo|video|essay|slogan)\b", "creative"),
)

_MEDIUM_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(?:create|sign\s*up\s+for|register)\s+(?:an?\s+)?account\b", "account"),
    (r"\blog\s*in\s+required\b", "login"),
    (r"\bmust\s+(?:be\s+)?logged\s+in\b", "login"),
    (r"\bnewsletter\b", "newsletter"),
    (r"\bfollow\s+(?:us\s+)?on\s+(?:instagram|facebook|twitter|x|tiktok)\b", "social"),
    (r"\blike\s+(?:our\s+)?(?:facebook|page|post)\b", "social"),
    (r"\bshare\s+(?:this|on)\b", "social"),
    (r"\bmultiple\s+steps?\b", "multi_step"),
)

_EASY_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\benter\s+your\s+details\b", "web_form"),
    (r"\bname\s+and\s+email\b", "name_email"),
    (r"\bemail\s+(?:address\s+)?(?:only\s+)?(?:to\s+)?enter\b", "email"),
    (r"\bsimple\s+(?:online\s+)?form\b", "web_form"),
    (r"\bonline\s+entry\s+form\b", "web_form"),
    (r"\banswer\s+the\s+question", "one_question"),
    (r"\bwebsite\b", "website"),
    (r"\bgleam\b", "gleam"),
)

_UNDESIRABLE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bfree\s+spins?\b", "casino"),
    (r"\bno\s+deposit\b", "casino"),
    (r"\bcasino\b", "casino"),
    (r"\bgambling\b", "gambling"),
    (r"\blottery\b", "lottery"),
    # Strong crypto signals only — bare nav labels like a sitewide "Crypto"
    # category link must not poison ordinary product giveaways.
    (r"\bcryptocurrenc", "crypto"),
    (r"\bbitcoin\b", "crypto"),
    (r"\bethereum\b", "crypto"),
    (r"\b\w+\s+token\s+airdrop\b", "crypto"),
    (r"\btoken\s+airdrop\b", "crypto"),
    (r"\bnft\s+giveaway\b", "crypto"),
    (r"\bwin\s+(?:free\s+)?(?:crypto|bitcoin|ethereum|nft)s?\b", "crypto"),
    (r"\bcrypto\s+giveaway\b", "crypto"),
    (r"\bsurvey\s+(?:funnel|only)\b", "survey"),
    (r"\bcomplete\s+(?:this\s+)?survey\b", "survey"),
    (r"\blead[- ]?gen", "survey"),
)

# Applied only against explicit prize/title/category fields (never full page HTML).
_CRYPTO_FIELD_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bcrypto\b", "crypto"),
    (r"\bnft\b", "crypto"),
    (r"\bairdrop\b", "crypto"),
    (r"\bbitcoin\b", "crypto"),
    (r"\bethereum\b", "crypto"),
)

_EXPIRED_PATTERNS: tuple[str, ...] = (
    r"\bthis\s+competition\s+has\s+closed\b",
    r"\bcompetition\s+has\s+closed\b",
    r"\bgiveaway\s+has\s+ended\b",
    r"\bhas\s+ended\b",
    r"\bexpired\b",
    r"\bno\s+longer\s+(?:open|available)\b",
    r"\bconcours\s+termin",
    r"\bjeu\s+clotur",
)

_NO_PURCHASE = re.compile(
    r"\bno\s+purchase\s+(?:necessary|required)\b|\bpurchase\s+required\s*:\s*no\b|"
    r"\bfree\s+to\s+enter\b|\bfree\s+online\s+competition",
    re.IGNORECASE,
)
_PURCHASE_YES = re.compile(
    r"\bpurchase\s+required\s*:\s*yes\b|"
    r"(?<!\bno\s)\bpurchase\s+required\b(?!\s*:?\s*no\b)",
    re.IGNORECASE,
)

_WORLDWIDE = re.compile(
    r"\bworldwide\b|\binternational\b|\bopen\s+(?:to\s+)?(?:all\s+)?countries\b|"
    r"\banywhere\s+in\s+the\s+world\b",
    re.IGNORECASE,
)
_UK_ONLY = re.compile(
    r"\buk\s+residents?\s+only\b|\bunited\s+kingdom\s+only\b|"
    r"\bonly\s+(?:open\s+to\s+)?(?:uk|united\s+kingdom)\b|"
    r"\buk\s+entrants?\b|\bavailable\s+in\s+united\s+kingdom\b|"
    r"\bopen\s+to\s+united\s+kingdom\b",
    re.IGNORECASE,
)
_US_ONLY = re.compile(
    r"\bus\s+residents?\s+only\b|\bunited\s+states\s+only\b|"
    r"\bonly\s+(?:open\s+to\s+)?(?:us|u\.s\.|united\s+states)\b|"
    r"\blegal\s+resident(?:s)?\s+of\s+the\s+united\s+states\b|"
    r"\bavailable\s+in\s+united\s+states\b|\bopen\s+to\s+united\s+states\b",
    re.IGNORECASE,
)
_FRANCE = re.compile(
    r"\bfrance\s+only\b|\bopen\s+to\s+(?:france|french\s+residents)\b|"
    r"\bresidents?\s+(?:of\s+)?france\b|\belligible\s+france\b|"
    r"\bfrance\s+(?:et|/)\s*(?:belgique|dom|tom)",
    re.IGNORECASE,
)
_EU = re.compile(
    r"\beu\s+(?:only|residents)\b|\beuropean\s+union\b|\beurope\s+only\b",
    re.IGNORECASE,
)
_CANADA = re.compile(
    r"\bcanada\s+only\b|\bcanadian\s+residents?\s+only\b|\bavailable\s+in\s+canada\b",
    re.IGNORECASE,
)
_FRANCE_EXCLUDED = re.compile(
    r"\bexclud(?:e|ing|es)\s+france\b|\bnot\s+(?:open|available)\s+(?:in|to)\s+france\b",
    re.IGNORECASE,
)


def _hits(blob: str, patterns: tuple[tuple[str, str], ...]) -> list[str]:
    found: list[str] = []
    for pattern, label in patterns:
        if not label:
            continue
        if re.search(pattern, blob, re.IGNORECASE):
            found.append(label)
    return found


def classify_entry_friction(
    *,
    instructions: str | None = None,
    entry_method_text: str | None = None,
    body: str | None = None,
    purchase_required_text: str | None = None,
) -> tuple[EntryFriction, str | None]:
    """Return friction + a coarse entry_method label from explicit instructions."""
    blob = normalize_text(
        " ".join(p for p in (instructions, entry_method_text, body) if p)
    )
    if not blob.strip():
        return EntryFriction.UNKNOWN, None

    hard = _hits(blob, _HARD_PATTERNS)
    # Explicit "Purchase required: No" (Giveario fact) must not count as hard.
    if purchase_required_text and normalize_text(purchase_required_text.strip()) in {
        "no",
        "false",
        "0",
        "n",
    }:
        hard = [h for h in hard if h != "purchase_required"]
    if _NO_PURCHASE.search(blob):
        hard = [h for h in hard if h != "purchase_required"]
    medium = _hits(blob, _MEDIUM_PATTERNS)
    easy = _hits(blob, _EASY_PATTERNS)


    method: str | None = None
    for label in (*easy, *medium, *hard):
        method = label
        break
    if entry_method_text:
        et = normalize_text(entry_method_text)
        if "gleam" in et:
            method = "gleam"
        elif "instagram" in et:
            method = "instagram"
        elif "facebook" in et:
            method = "facebook"
        elif "website" in et or "web form" in et or "web_form" in et:
            method = "web_form"
        elif "email" in et:
            method = "email"

    if hard:
        return EntryFriction.HARD, method or hard[0]
    if medium:
        return EntryFriction.MEDIUM, method or medium[0]
    if easy:
        # Plain Gleam without mandatory social spam → easy
        return EntryFriction.EASY, method or easy[0]
    if entry_method_text and normalize_text(entry_method_text) in {
        "website",
        "web form",
        "online",
        "form",
    }:
        return EntryFriction.EASY, "web_form"
    return EntryFriction.UNKNOWN, method


def infer_geo_scope(restriction: str | None) -> GeoScope:
    if not restriction or not restriction.strip():
        return GeoScope.UNKNOWN
    text = restriction.strip()
    if _WORLDWIDE.search(text):
        return GeoScope.WORLDWIDE
    if _UK_ONLY.search(text) or normalize_text(text) in {"uk", "united kingdom"}:
        return GeoScope.UK
    if _US_ONLY.search(text) or normalize_text(text) in {
        "us",
        "u.s.",
        "united states",
        "usa",
    }:
        return GeoScope.US
    if _CANADA.search(text) or normalize_text(text) in {"canada", "ca"}:
        return GeoScope.CANADA
    if _FRANCE.search(text):
        return GeoScope.FRANCE
    if _EU.search(text):
        return GeoScope.EU
    # Explicit country-ish text without a known bucket
    if re.search(r"\bonly\b|\bresidents?\b|\bavailable\s+in\b|\bopen\s+to\b", text, re.IGNORECASE):
        return GeoScope.SPECIFIC
    return GeoScope.UNKNOWN


def infer_eligible_france(
    *,
    restriction: str | None = None,
    geo_scope: GeoScope | None = None,
) -> bool | None:
    """
    eligible_france from explicit restriction text only.

    Worldwide → True unless France is excluded.
    UK/US-only → False.
    Ambiguous → None.
    """
    scope = geo_scope or infer_geo_scope(restriction)
    text = restriction or ""
    if _FRANCE_EXCLUDED.search(text):
        return False
    if scope == GeoScope.WORLDWIDE:
        return True
    if scope in {GeoScope.FRANCE, GeoScope.EU}:
        return True
    if scope in {GeoScope.UK, GeoScope.US, GeoScope.CANADA}:
        return False
    if scope == GeoScope.SPECIFIC:
        # Explicit list that mentions France
        if _FRANCE.search(text) and not _FRANCE_EXCLUDED.search(text):
            return True
        return False if re.search(r"\bonly\b", text, re.IGNORECASE) else None
    return None


def detect_undesirable(
    *,
    title: str | None = None,
    body: str | None = None,
    prize: str | None = None,
    category: str | None = None,
) -> list[str]:
    """
    Flag paid/gambling/crypto/etc. from giveaway-specific text only.

    Pass cleaned candidate text (title/prize/category/description/rules) — never
    full-page navigation/sidebar HTML.
    """
    field_blob = "\n".join(
        p for p in (title, prize, category) if p and str(p).strip()
    )
    body_blob = body or ""
    combined = f"{field_blob}\n{body_blob}"

    reasons = _hits(combined, _UNDESIRABLE_PATTERNS)
    # Short-token crypto labels only count on title/prize/category — not body —
    # so a sidebar "Crypto" link cannot reject a back-massager giveaway.
    reasons.extend(_hits(normalize_text(field_blob), _CRYPTO_FIELD_PATTERNS))

    if any(re.search(p, combined, re.IGNORECASE) for p in _EXPIRED_PATTERNS):
        reasons.append("expired")
    hard_hits = _hits(normalize_text(combined), _HARD_PATTERNS)
    if _NO_PURCHASE.search(combined):
        hard_hits = [h for h in hard_hits if h != "purchase_required"]
    for h in hard_hits:
        if h in {"purchase_required", "paid_entry", "postal_only"}:
            reasons.append(h)
    seen: set[str] = set()
    out: list[str] = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def infer_free_entry(
    *,
    body: str | None = None,
    purchase_required_text: str | None = None,
    free_hint: bool | None = None,
) -> bool | None:
    if free_hint is not None:
        return free_hint
    if purchase_required_text is not None:
        pr = normalize_text(purchase_required_text.strip())
        if pr in {"no", "false", "0", "n"}:
            return True
        if pr in {"yes", "true", "1", "y"}:
            return False
    blob = " ".join(p for p in (purchase_required_text, body) if p)
    if not blob.strip():
        return None
    if _NO_PURCHASE.search(blob):
        return True
    if _PURCHASE_YES.search(blob):
        return False
    if re.search(r"\bpaid\s+entr(?:y|ies)\b|\bentry\s+fee\b", blob, re.IGNORECASE):
        return False
    return None


def discovery_priority(
    *,
    free_entry: bool | None,
    friction: EntryFriction,
    eligible_france: bool | None,
    geo_scope: GeoScope,
) -> int:
    """Approximate preference order (lower is better)."""
    if free_entry is False:
        return 90
    if friction == EntryFriction.HARD:
        return 80
    worldwide = geo_scope == GeoScope.WORLDWIDE
    fr_eu = eligible_france is True or geo_scope in {GeoScope.FRANCE, GeoScope.EU}
    if worldwide and friction == EntryFriction.EASY and free_entry is True:
        return 1
    if fr_eu and friction == EntryFriction.EASY and free_entry is not False:
        return 2
    if worldwide and friction == EntryFriction.MEDIUM and free_entry is not False:
        return 3
    if friction == EntryFriction.EASY and free_entry is not False:
        return 4
    if friction == EntryFriction.MEDIUM:
        return 5
    if friction == EntryFriction.UNKNOWN:
        return 6
    return 70


def assess_entry(
    *,
    title: str | None = None,
    body: str | None = None,
    instructions: str | None = None,
    entry_method_text: str | None = None,
    restriction: str | None = None,
    purchase_required_text: str | None = None,
    free_hint: bool | None = None,
    prize: str | None = None,
    category: str | None = None,
) -> EntryAssessment:
    friction, method = classify_entry_friction(
        instructions=instructions,
        entry_method_text=entry_method_text,
        body=body,
        purchase_required_text=purchase_required_text,
    )
    geo_scope = infer_geo_scope(restriction)
    eligible = infer_eligible_france(restriction=restriction, geo_scope=geo_scope)
    free_entry = infer_free_entry(
        body=body,
        purchase_required_text=purchase_required_text,
        free_hint=free_hint,
    )
    bad = detect_undesirable(
        title=title,
        prize=prize,
        category=category,
        body=" ".join(filter(None, [body, instructions])),
    )
    if purchase_required_text and normalize_text(purchase_required_text.strip()) in {
        "no",
        "false",
        "0",
        "n",
    }:
        bad = [b for b in bad if b != "purchase_required"]
    if free_hint is True or (purchase_required_text and normalize_text(purchase_required_text.strip()) in {"no", "n"}):
        bad = [b for b in bad if b != "purchase_required"]
    requires_purchase = None
    if free_entry is False or "purchase_required" in bad or "paid_entry" in bad:
        requires_purchase = True
    elif free_entry is True:
        requires_purchase = False

    blob = normalize_text(" ".join(filter(None, [instructions, entry_method_text, body])))
    medium_hits = _hits(blob, _MEDIUM_PATTERNS)
    requires_social: bool | None = None
    if method in {"instagram", "facebook", "social"} or "social" in medium_hits:
        requires_social = True

    skip_reasons = tuple(bad)
    # Skip Gemini when deterministic undesirability is clear.
    # Referral / optional social presence is handled by entry_acceptability, not here.
    skip_gemini = bool(
        set(skip_reasons)
        & {
            "purchase_required",
            "paid_entry",
            "postal_only",
            "casino",
            "gambling",
            "lottery",
            "crypto",
            "survey",
            "expired",
        }
    )
    return EntryAssessment(
        entry_friction=friction,
        free_entry=free_entry,
        requires_purchase=requires_purchase,
        requires_social=requires_social,
        entry_method=method,
        geo_scope=geo_scope,
        geo_restriction=restriction.strip() if restriction and restriction.strip() else None,
        eligible_france=eligible,
        skip_gemini=skip_gemini,
        skip_reasons=skip_reasons,
        discovery_priority=discovery_priority(
            free_entry=free_entry,
            friction=friction,
            eligible_france=eligible,
            geo_scope=geo_scope,
        ),
    )
