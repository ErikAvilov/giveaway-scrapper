"""Gleam.io campaign platform parser (not an aggregator).

Parses campaign HTML served over ordinary HTTP (Scrapling chrome impersonation).
Does not automate entry, OAuth, CAPTCHA, or referrals.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from html import unescape
from typing import Any
from urllib.parse import urlparse

from app.extraction.entry_assessment import EntryFriction, GeoScope, infer_eligible_france

PLATFORM = "gleam"

# https://gleam.io/<key> or https://gleam.io/<key>/<slug>
_GLEAM_PATH = re.compile(
    r"^/(?P<key>[A-Za-z0-9]{4,12})(?:/(?P<slug>[A-Za-z0-9\-._]+))?/?$",
)

_NON_CAMPAIGN_KEYS = frozenset(
    {
        "giveaways",
        "app",
        "blog",
        "docs",
        "help",
        "tools",
        "pricing",
        "integrations",
        "features",
        "templates",
        "partners",
        "about",
        "legal",
        "careers",
        "contact",
        "login",
        "signup",
        "auth",
        "dashboard",
        "shopify-install",
        "cms_pages",
        "signed-in",
    }
)

_SOCIAL_TYPES = frozenset(
    {
        "twitter_follow",
        "twitter_retweet",
        "twitter_tweet",
        "twitter_hashtags",
        "facebook_like",
        "facebook_visit",
        "facebook_check_in",
        "instagram_follow",
        "instagram_visit_profile",
        "instagram_view_post",
        "tiktok_follow",
        "tiktok_view_video",
        "youtube_subscribe",
        "youtube_visit_channel",
        "youtube_watch_video",
        "spotify_follow",
        "spotify_listen",
        "twitch_follow",
        "discord_join_server",
    }
)

_EMAIL_TYPES = frozenset(
    {
        "email_subscribe",
        "newsletter",
        "email_submit",
    }
)

_REFERRAL_TYPES = frozenset(
    {
        "referral",
        "refer_friend",
        "share_action",
        "custom_refer",
    }
)

_UPLOAD_TYPES = frozenset(
    {
        "upload_file",
        "upload_image",
        "upload_video",
        "instagram_upload_photo",
        "media_upload",
        "submit_content",
    }
)

_EASY_TYPES = frozenset(
    {
        "email_subscribe",
        "newsletter",
        "visit_website",
        "visit_page",
        "hidden",
        "bonus",
        "custom_action",
        "question",
        "choose_image",
    }
)


@dataclass(slots=True)
class GleamEntryAction:
    entry_type: str
    mandatory: bool
    worth: int | None = None
    provider: str | None = None
    requires_authentication: bool = False
    actions_required: int | None = None
    category: str = "other"  # social | email | referral | upload | visit | other


@dataclass(slots=True)
class GleamCampaign:
    platform: str = PLATFORM
    platform_campaign_id: str | None = None
    campaign_slug: str | None = None
    canonical_url: str | None = None
    entry_url: str | None = None
    title: str | None = None
    prize: str | None = None
    description: str | None = None
    organizer: str | None = None
    organizer_url: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    terms_html: str | None = None
    terms_text: str | None = None
    geo_restriction: str | None = None
    geo_scope: str | None = None
    eligible_france: bool | None = None
    login_required: bool | None = None
    login_types: list[str] = field(default_factory=list)
    require_contact_info: bool | None = None
    has_paid_entry_methods: bool | None = None
    actions_required: int | None = None
    mandatory_actions: list[GleamEntryAction] = field(default_factory=list)
    optional_actions: list[GleamEntryAction] = field(default_factory=list)
    referral_actions: list[GleamEntryAction] = field(default_factory=list)
    social_actions: list[GleamEntryAction] = field(default_factory=list)
    email_actions: list[GleamEntryAction] = field(default_factory=list)
    upload_actions: list[GleamEntryAction] = field(default_factory=list)
    entry_friction: str = EntryFriction.UNKNOWN.value
    free_entry: bool | None = None
    finished: bool | None = None
    raw_entry_types: list[str] = field(default_factory=list)

    def to_meta(self) -> dict[str, Any]:
        """Normalized platform metadata for candidate / future dedup."""
        return {
            "platform": self.platform,
            "platform_campaign_id": self.platform_campaign_id,
            "campaign_slug": self.campaign_slug,
            "actions_required": self.actions_required,
            "mandatory_entry_types": [a.entry_type for a in self.mandatory_actions],
            "optional_entry_types": [a.entry_type for a in self.optional_actions],
            "referral_entry_types": [a.entry_type for a in self.referral_actions],
            "social_entry_types": [a.entry_type for a in self.social_actions],
            "email_entry_types": [a.entry_type for a in self.email_actions],
            "upload_entry_types": [a.entry_type for a in self.upload_actions],
            "mandatory_actions": [
                {"entry_type": a.entry_type, "mandatory": True}
                for a in self.mandatory_actions
            ],
            "optional_actions": [
                {"entry_type": a.entry_type, "mandatory": False}
                for a in self.optional_actions
            ],
            "login_required": self.login_required,
            "login_types": list(self.login_types),
            "has_paid_entry_methods": self.has_paid_entry_methods,
            "finished": self.finished,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.start_at:
            payload["start_at"] = self.start_at.isoformat()
        if self.end_at:
            payload["end_at"] = self.end_at.isoformat()
        return payload


def is_gleam_host(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower().removeprefix("www.")
    except (TypeError, ValueError, AttributeError):
        return False
    return host == "gleam.io" or host.endswith(".gleam.io")


def parse_gleam_campaign_url(url: str) -> tuple[str | None, str | None]:
    """Return (campaign_key, slug) when URL looks like a Gleam campaign page."""
    if not is_gleam_host(url):
        return None, None
    path = urlparse(url).path or "/"
    match = _GLEAM_PATH.match(path)
    if not match:
        return None, None
    key = match.group("key")
    slug = match.group("slug")
    if key.lower() in _NON_CAMPAIGN_KEYS:
        return None, None
    return key, slug


def gleam_canonical_url(campaign_id: str, slug: str | None = None) -> str:
    if slug:
        return f"https://gleam.io/{campaign_id}/{slug}"
    return f"https://gleam.io/{campaign_id}"


def gleam_identity_from_url(url: str) -> dict[str, str] | None:
    key, slug = parse_gleam_campaign_url(url)
    if not key:
        return None
    return {
        "platform": PLATFORM,
        "platform_campaign_id": key,
        "campaign_slug": slug or "",
        "entry_url": gleam_canonical_url(key, slug),
        "canonical_hint": gleam_canonical_url(key, slug),
    }


def _category_for(entry_type: str) -> str:
    et = (entry_type or "").lower()
    if et in _REFERRAL_TYPES or "refer" in et:
        return "referral"
    if et in _UPLOAD_TYPES or "upload" in et or et.endswith("_media"):
        return "upload"
    if et in _EMAIL_TYPES or "email" in et or "newsletter" in et:
        return "email"
    if et in _SOCIAL_TYPES or any(
        p in et for p in ("twitter", "facebook", "instagram", "tiktok", "youtube", "spotify", "twitch", "discord")
    ):
        return "social"
    if "visit" in et or et in {"visit_website", "visit_page"}:
        return "visit"
    return "other"


def _ts_to_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return None
    # Gleam uses seconds since epoch
    if ts > 10_000_000_000:  # ms
        ts //= 1000
    return datetime.fromtimestamp(ts, tz=UTC)


def _strip_html(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = unescape(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def _extract_geo_from_terms(terms_text: str | None) -> tuple[str | None, GeoScope]:
    if not terms_text:
        return None, GeoScope.UNKNOWN
    lower = terms_text.lower()
    # Prefer explicit worldwide / country-only phrases from terms.
    if re.search(r"\bopen worldwide\b|\bworldwide\b.*\bvoid where prohibited\b", lower):
        return "Worldwide", GeoScope.WORLDWIDE
    if re.search(r"\buk\s+residents?\s+only\b|\bunited\s+kingdom\s+only\b", lower):
        return "UK residents only", GeoScope.UK
    if re.search(r"\bus\s+residents?\s+only\b|\bunited\s+states\s+(?:residents?\s+)?only\b", lower):
        return "US residents only", GeoScope.US
    if re.search(r"\bonly open to (?:legal\s+)?residents of ([^.\n]{3,80})", lower):
        m = re.search(r"only open to (?:legal\s+)?residents of ([^.\n]{3,80})", terms_text, re.IGNORECASE)
        if m:
            return m.group(0).strip()[:300], GeoScope.SPECIFIC
    return None, GeoScope.UNKNOWN


def extract_init_campaign_payload(html: str) -> dict[str, Any] | None:
    """Extract the JSON object passed to Angular initCampaign(...)."""
    if "initCampaign(" not in html and "initCampaign" not in html:
        return None
    patterns = (
        r'ng-init="(initCampaign\(.+\))"',
        r"ng-init='(initCampaign\(.+\))'",
        r"(initCampaign\(.+\))",
    )
    match = None
    for pattern in patterns:
        match = re.search(pattern, html, re.DOTALL)
        if match:
            break
    if not match:
        return None
    attr = unescape(match.group(1))
    start = attr.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    quote: str | None = None
    for i, ch in enumerate(attr[start:], start):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                in_str = False
            continue
        if ch in {'"', "'"}:
            in_str = True
            quote = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    payload = json.loads(attr[start : i + 1])
                except json.JSONDecodeError:
                    return None
                return payload if isinstance(payload, dict) else None
    return None


def _action_from_em(em: dict[str, Any]) -> GleamEntryAction:
    entry_type = str(em.get("entry_type") or "unknown")
    worth = em.get("worth")
    try:
        worth_i = int(worth) if worth is not None else None
    except (TypeError, ValueError):
        worth_i = None
    ar = em.get("actions_required")
    try:
        ar_i = int(ar) if ar is not None else None
    except (TypeError, ValueError):
        ar_i = None
    return GleamEntryAction(
        entry_type=entry_type,
        mandatory=bool(em.get("mandatory")),
        worth=worth_i,
        provider=str(em["provider"]) if em.get("provider") else None,
        requires_authentication=bool(em.get("requires_authentication")),
        actions_required=ar_i,
        category=_category_for(entry_type),
    )


def assess_gleam_friction(
    *,
    actions_required: int | None,
    mandatory: list[GleamEntryAction],
    optional: list[GleamEntryAction],
    login_required: bool,
    has_paid: bool,
) -> EntryFriction:
    """Deterministic friction from Gleam action lists — per campaign, not platform reputation."""
    if has_paid:
        return EntryFriction.HARD

    referral = [a for a in mandatory + optional if a.category == "referral"]
    upload = [a for a in mandatory + optional if a.category == "upload"]
    creative = [
        a
        for a in mandatory + optional
        if any(x in a.entry_type for x in ("blog", "essay", "creative", "video_submit", "photo_submit"))
    ]
    if referral or upload or creative:
        return EntryFriction.HARD

    mand_social = [a for a in mandatory if a.category == "social"]
    mand_count = len(mandatory)
    mand_social_n = len(mand_social)
    # Prefer explicit campaign actions_required when present.
    required_n = actions_required if actions_required is not None else mand_count

    if required_n >= 6 or mand_social_n >= 4:
        return EntryFriction.HARD
    if login_required or required_n >= 3 or mand_social_n >= 2:
        return EntryFriction.MEDIUM
    if required_n <= 2 and mand_count <= 2:
        # one/two straightforward actions (email, visit, simple question)
        return EntryFriction.EASY
    if required_n <= 2 and all(
        a.category in {"email", "visit", "other"} or a.entry_type in _EASY_TYPES for a in mandatory
    ):
        return EntryFriction.EASY
    if required_n <= 4:
        return EntryFriction.MEDIUM
    return EntryFriction.UNKNOWN


def parse_gleam_campaign_html(html: str, *, page_url: str | None = None) -> GleamCampaign | None:
    """Parse a Gleam campaign page HTML body into structured fields."""
    payload = extract_init_campaign_payload(html)
    if not payload:
        return None

    campaign = payload.get("campaign") if isinstance(payload.get("campaign"), dict) else {}
    incentive = payload.get("incentive") if isinstance(payload.get("incentive"), dict) else {}
    entry_methods = payload.get("entry_methods") if isinstance(payload.get("entry_methods"), list) else []

    key = str(campaign.get("key") or "") or None
    url_key, url_slug = parse_gleam_campaign_url(page_url) if page_url else (None, None)
    key = key or url_key
    slug = url_slug

    actions = [_action_from_em(em) for em in entry_methods if isinstance(em, dict)]
    mandatory = [a for a in actions if a.mandatory]
    optional = [a for a in actions if not a.mandatory]
    referral = [a for a in actions if a.category == "referral"]
    social = [a for a in actions if a.category == "social"]
    email = [a for a in actions if a.category == "email"]
    upload = [a for a in actions if a.category == "upload"]

    terms_html = campaign.get("terms_and_conditions")
    terms_text = _strip_html(str(terms_html) if terms_html else None)
    geo_text, geo_scope = _extract_geo_from_terms(terms_text)
    eligible = infer_eligible_france(restriction=geo_text, geo_scope=geo_scope)

    login_types = [str(x) for x in (campaign.get("login_types") or []) if x]
    login_first = bool(campaign.get("login_first"))
    # Auth required on any mandatory method ⇒ treat as login friction.
    login_required = login_first or any(a.requires_authentication for a in mandatory)

    try:
        actions_required = int(incentive["actions_required"]) if incentive.get("actions_required") is not None else None
    except (TypeError, ValueError):
        actions_required = None

    has_paid = bool(campaign.get("has_paid_entry_methods"))
    friction = assess_gleam_friction(
        actions_required=actions_required,
        mandatory=mandatory,
        optional=optional,
        login_required=login_required,
        has_paid=has_paid,
    )

    title = str(campaign.get("name") or incentive.get("name") or "") or None
    prize = title  # Gleam often uses campaign name as the prize headline
    description = _strip_html(str(incentive.get("description") or "") or None)
    organizer = str(campaign.get("site_name") or "") or None
    organizer_url = str(campaign.get("site_url") or "") or None

    free_entry: bool | None = None
    if has_paid:
        free_entry = False
    elif terms_text and re.search(r"no purchase (is )?necessary|no purchase required", terms_text, re.IGNORECASE):
        free_entry = True

    canonical = gleam_canonical_url(key, slug) if key else page_url

    return GleamCampaign(
        platform_campaign_id=key,
        campaign_slug=slug,
        canonical_url=canonical,
        entry_url=canonical,
        title=title,
        prize=prize,
        description=description,
        organizer=organizer,
        organizer_url=organizer_url,
        start_at=_ts_to_dt(campaign.get("starts_at")),
        end_at=_ts_to_dt(campaign.get("ends_at")),
        terms_html=str(terms_html)[:8000] if terms_html else None,
        terms_text=(terms_text[:4000] if terms_text else None),
        geo_restriction=geo_text,
        geo_scope=geo_scope.value,
        eligible_france=eligible,
        login_required=login_required,
        login_types=login_types,
        require_contact_info=bool(campaign.get("require_contact_info"))
        if campaign.get("require_contact_info") is not None
        else None,
        has_paid_entry_methods=has_paid,
        actions_required=actions_required,
        mandatory_actions=mandatory,
        optional_actions=optional,
        referral_actions=referral,
        social_actions=social,
        email_actions=email,
        upload_actions=upload,
        entry_friction=friction.value,
        free_entry=free_entry,
        finished=bool(campaign.get("finished")) if campaign.get("finished") is not None else None,
        raw_entry_types=[a.entry_type for a in actions],
    )


def response_html(response: Any) -> str:
    """Best-effort HTML string from a Scrapling/Fetcher response or Selector."""
    for attr in ("html_content", "body", "text"):
        value = getattr(response, attr, None)
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if isinstance(value, str) and value:
            return value
    # Prefer ng-init attribute when the DOM was already parsed (fixtures / Selector).
    try:
        nodes = response.css("[ng-init]::attr(ng-init)")
        if nodes:
            value = str(nodes[0]).strip()
            if value:
                return f'<div ng-init="{value}"></div>'
    except (TypeError, ValueError, AttributeError):
        pass
    html = getattr(response, "html", None)
    if callable(html):
        try:
            return str(html())
        except (TypeError, ValueError, AttributeError):
            pass
    return str(response)
