"""Entry acceptability: reject only when no non-public participation path exists.

Public social actions (comment, tag, share, story, …) may exist as optional bonus
methods. Follows / subscriptions / visits / email are acceptable.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.extraction.entry_assessment import normalize_text

REJECTION_REASON = "requires public social-media action"


class ActionClass(StrEnum):
    NON_PUBLIC = "non_public"
    PUBLIC_SOCIAL = "public_social"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Action-type classification (platform metadata)
# ---------------------------------------------------------------------------

NON_PUBLIC_ACTION_TYPES: frozenset[str] = frozenset(
    {
        # Visit / click
        "visit_website",
        "visit_page",
        "visit",
        "click",
        "hidden",
        "bonus",
        "custom_action",
        "choose_image",
        "question",
        "trivia",
        "quiz",
        "poll",
        # Email / form / account
        "email_subscribe",
        "email_submit",
        "newsletter",
        "register",
        "signup",
        "login",
        "account",
        # Follow / subscribe (acceptable)
        "twitter_follow",
        "instagram_follow",
        "tiktok_follow",
        "youtube_subscribe",
        "twitch_follow",
        "spotify_follow",
        "facebook_like",
        "facebook_visit",
        "facebook_check_in",
        "instagram_visit_profile",
        "instagram_view_post",
        "tiktok_view_video",
        "youtube_visit_channel",
        "youtube_watch_video",
        "spotify_listen",
        "discord_join_server",
        "discord_join",
        "pinterest_follow",
        "linkedin_follow",
        "soundcloud_follow",
    }
)

PUBLIC_SOCIAL_ACTION_TYPES: frozenset[str] = frozenset(
    {
        "twitter_retweet",
        "twitter_tweet",
        "twitter_hashtags",
        "twitter_comment",
        "twitter_reply",
        "twitter_quote",
        "facebook_share",
        "facebook_comment",
        "facebook_post",
        "instagram_comment",
        "instagram_upload_photo",
        "instagram_post",
        "instagram_story",
        "tiktok_comment",
        "tiktok_share",
        "tiktok_post",
        "share_action",
        "upload_file",
        "upload_image",
        "upload_video",
        "media_upload",
        "submit_content",
        "blog",
        "essay",
        "creative",
        "video_submit",
        "photo_submit",
        "referral",
        "refer_friend",
        "custom_refer",
        "public_referral",
    }
)

_NON_PUBLIC_SUBSTR = (
    "follow",
    "subscribe",
    "newsletter",
    "email",
    "visit",
    "watch",
    "listen",
    "view_post",
    "view_video",
    "join_server",
    "discord",
    "login",
    "sign_up",
    "signup",
    "register",
    "question",
    "trivia",
    "checkbox",
)

_PUBLIC_SUBSTR = (
    "comment",
    "retweet",
    "tweet",
    "hashtag",
    "share",
    "repost",
    "reshare",
    "story",
    "upload",
    "submit_content",
    "tag_friend",
    "tag_a_friend",
    "mention",
    "quote",
    "refer",
    "referral",
)

# Text patterns for PUBLIC social actions (instruction prose).
_PUBLIC_SOCIAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\btag\s+(?:a\s+)?(?:friend|friends|\d+\s+friends?)\b", "tag_friend"),
    (r"\btag\s+\d+\b", "tag_friend"),
    (r"\bmention\s+(?:a\s+)?(?:friend|friends|\d+\s+friends?)\b", "mention_friend"),
    (r"\bidentifi(?:ez|er)\s+(?:un\s+)?ami\b", "tag_friend_fr"),
    (r"\btagu(?:ez|er)\s+(?:un\s+)?ami\b", "tag_friend_fr"),
    (r"\bmentionn(?:ez|er)\s+(?:un\s+)?ami\b", "mention_friend_fr"),
    (r"\binvit(?:ez|er)\s+(?:des\s+)?amis?\s+publiquement\b", "invite_friends_fr"),
    (r"\bcomment\s+below\b", "comment"),
    (r"\bleave\s+a\s+comment\b", "comment"),
    (r"\bpost\s+a\s+comment\b", "comment"),
    (r"\bcomment\s+on\s+(?:this\s+)?(?:post|photo|video|reel)\b", "comment"),
    (r"\bcomment(?:ez|er)\b", "comment_fr"),
    (r"\blaissez?\s+un\s+commentaire\b", "comment_fr"),
    (r"\bshare\s+(?:this\s+)?(?:post|photo|video|reel)\b", "share"),
    (r"\bshare\s+to\s+(?:your\s+)?(?:story|stories)\b", "story"),
    (r"\bshare\s+on\s+(?:instagram|facebook|tiktok|twitter|x)\b", "share"),
    (r"\brepost\b", "repost"),
    (r"\bretweet\b", "retweet"),
    (r"\bquote[- ]?post\b", "quote_post"),
    (r"\breshare\b", "reshare"),
    (r"\bpartagez?\s+(?:cette\s+)?(?:publication|poste?|photo|vid[eé]o)\b", "share_fr"),
    (r"\brepartagez?\b", "reshare_fr"),
    (r"\brepubliez?\b", "repost_fr"),
    (r"\bpubliez?\s+en\s+story\b", "story_fr"),
    (r"\bpartagez?\s+(?:en|sur\s+(?:votre\s+)?)story\b", "story_fr"),
    (r"\bpost\s+(?:a\s+)?(?:photo|video|reel|story)\b", "post_content"),
    (r"\bpost\s+to\s+(?:instagram|facebook|tiktok|twitter|x)\b", "post_content"),
    (r"\bpublish\s+(?:a\s+)?(?:post|photo|video)\b", "post_content"),
    (r"\bcreate\s+(?:a\s+)?(?:post|story|video|ugc)\b", "ugc"),
    (r"\buser[- ]generated\s+content\b", "ugc"),
    (r"\bpubliez?\s+(?:une\s+)?(?:photo|vid[eé]o|publication)\b", "post_content_fr"),
    (r"\buse\s+(?:the\s+)?hashtag\b", "hashtag"),
    (r"\bpost\s+(?:with\s+)?#\w+", "hashtag"),
    (r"\butilisez?\s+(?:le\s+)?hashtag\b", "hashtag_fr"),
    (r"\bpublic\s+(?:testimonial|review)\b", "testimonial"),
    (r"\bpublic\s+referral\s+post\b", "referral_post"),
)

# Non-public path signals in free text.
_NON_PUBLIC_TEXT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bfollow\b", "follow"),
    (r"\bsubscribe\b", "subscribe"),
    (r"\bnewsletter\b", "newsletter"),
    (r"\bemail\b", "email"),
    (r"\bvisit\b", "visit"),
    (r"\benter\s+(?:your\s+)?(?:name|email)\b", "form"),
    (r"\bcreate\s+an\s+account\b", "account"),
    (r"\blog\s*in\b", "login"),
    (r"\bjoin\s+(?:our\s+)?discord\b", "discord"),
    (r"\babonnez[- ]vous\b", "subscribe_fr"),
    (r"\bsuivez[- ]nous\b", "follow_fr"),
    (r"\bvisitez\b", "visit_fr"),
)

_OPTIONAL_MARKERS = re.compile(
    r"\b(?:optional|bonus|extra\s+entr(?:y|ies)|for\s+bonus|"
    r"optionnel|bonus\s+d[' ]?entr[eé]es?|pour\s+plus\s+d[' ]?entr[eé]es?)\b",
    re.IGNORECASE,
)

_MANDATORY_MARKERS = re.compile(
    r"\b(?:must|required|mandatory|to\s+enter|in\s+order\s+to\s+enter|"
    r"obligatoire|pour\s+participer|afin\s+de\s+participer)\b",
    re.IGNORECASE,
)


@dataclass(slots=True, frozen=True)
class EntryAcceptability:
    requires_public_social_action: bool | None
    entry_acceptable: bool | None
    entry_rejection_reason: str | None
    matched_signals: tuple[str, ...] = ()
    has_non_public_entry_path: bool | None = None
    public_social_actions_available: bool | None = None
    minimum_required_actions: int | None = None
    non_public_actions_available: int | None = None

    @property
    def skip_gemini(self) -> bool:
        """Clear local reject — no need to spend Gemini on social gate."""
        return self.entry_acceptable is False


def classify_action_type(entry_type: str | None) -> ActionClass:
    """Classify a platform entry_type into non-public / public / unknown."""
    et = (entry_type or "").strip().lower()
    if not et:
        return ActionClass.UNKNOWN
    if et in NON_PUBLIC_ACTION_TYPES:
        return ActionClass.NON_PUBLIC
    if et in PUBLIC_SOCIAL_ACTION_TYPES:
        return ActionClass.PUBLIC_SOCIAL
    public_hit = any(s in et for s in _PUBLIC_SUBSTR)
    non_public_hit = any(s in et for s in _NON_PUBLIC_SUBSTR)
    if public_hit and not non_public_hit:
        return ActionClass.PUBLIC_SOCIAL
    if non_public_hit and not public_hit:
        return ActionClass.NON_PUBLIC
    if "follow" in et or "subscribe" in et:
        return ActionClass.NON_PUBLIC
    if public_hit:
        return ActionClass.PUBLIC_SOCIAL
    return ActionClass.UNKNOWN


def is_public_social_action_type(entry_type: str | None) -> bool:
    return classify_action_type(entry_type) == ActionClass.PUBLIC_SOCIAL


def is_non_public_action_type(entry_type: str | None) -> bool:
    return classify_action_type(entry_type) == ActionClass.NON_PUBLIC


def _action_fields(action: Any) -> tuple[str | None, bool | None]:
    et = getattr(action, "entry_type", None)
    if et is None and isinstance(action, dict):
        et = action.get("entry_type")
    mandatory = getattr(action, "mandatory", None)
    if mandatory is None and isinstance(action, dict):
        mandatory = action.get("mandatory")
    return (str(et) if et is not None else None, mandatory)


def _hits(blob: str, patterns: Sequence[tuple[str, str]]) -> list[str]:
    found: list[str] = []
    for pattern, label in patterns:
        if re.search(pattern, blob, re.IGNORECASE):
            found.append(label)
    return found


def assess_platform_actions(
    actions: Iterable[Any],
    *,
    actions_required: int | None = None,
) -> EntryAcceptability | None:
    """
    Determine whether a non-public valid entry path exists from platform metadata.

    Returns None when actions are empty / inconclusive (caller may use text/Gemini).
    """
    items = list(actions)
    if not items:
        return None

    non_public: list[str] = []
    public: list[str] = []
    unknown: list[str] = []
    mandatory_public: list[str] = []
    mandatory_non_public: list[str] = []
    any_mandatory = False

    for action in items:
        et, mandatory = _action_fields(action)
        kind = classify_action_type(et)
        label = et or "unknown"
        if kind == ActionClass.NON_PUBLIC:
            non_public.append(label)
            if mandatory is True:
                mandatory_non_public.append(label)
                any_mandatory = True
        elif kind == ActionClass.PUBLIC_SOCIAL:
            public.append(label)
            if mandatory is True:
                mandatory_public.append(label)
                any_mandatory = True
        else:
            unknown.append(label)
            if mandatory is True:
                any_mandatory = True

    n_non_public = len(non_public)
    n_public = len(public)
    public_available = n_public > 0
    signals = tuple(dict.fromkeys([*mandatory_public, *public[:8]]))

    # Explicitly mandatory public action(s) → reject.
    if mandatory_public:
        return EntryAcceptability(
            requires_public_social_action=True,
            entry_acceptable=False,
            entry_rejection_reason=REJECTION_REASON,
            matched_signals=tuple(dict.fromkeys(mandatory_public)),
            has_non_public_entry_path=False,
            public_social_actions_available=public_available,
            minimum_required_actions=actions_required,
            non_public_actions_available=n_non_public,
        )

    # "Complete any N actions" campaigns.
    if actions_required is not None and actions_required > 0:
        if n_non_public >= actions_required:
            return EntryAcceptability(
                requires_public_social_action=False,
                entry_acceptable=True,
                entry_rejection_reason=None,
                matched_signals=signals if public_available else (),
                has_non_public_entry_path=True,
                public_social_actions_available=public_available,
                minimum_required_actions=actions_required,
                non_public_actions_available=n_non_public,
            )
        if n_non_public + len(unknown) >= actions_required:
            return EntryAcceptability(
                requires_public_social_action=False,
                entry_acceptable=True,
                entry_rejection_reason=None,
                matched_signals=signals if public_available else (),
                has_non_public_entry_path=True,
                public_social_actions_available=public_available,
                minimum_required_actions=actions_required,
                non_public_actions_available=n_non_public,
            )
        if n_public > 0 and n_non_public < actions_required:
            return EntryAcceptability(
                requires_public_social_action=True,
                entry_acceptable=False,
                entry_rejection_reason=REJECTION_REASON,
                matched_signals=signals,
                has_non_public_entry_path=False,
                public_social_actions_available=True,
                minimum_required_actions=actions_required,
                non_public_actions_available=n_non_public,
            )
        return None

    # Classic mandatory/optional model (no pick-N quota).
    if n_non_public > 0:
        return EntryAcceptability(
            requires_public_social_action=False,
            entry_acceptable=True,
            entry_rejection_reason=None,
            matched_signals=signals if public_available else (),
            has_non_public_entry_path=True,
            public_social_actions_available=public_available,
            minimum_required_actions=len(mandatory_non_public) or None,
            non_public_actions_available=n_non_public,
        )

    # Only public methods available → no clean path.
    if n_public > 0 and not unknown:
        return EntryAcceptability(
            requires_public_social_action=True,
            entry_acceptable=False,
            entry_rejection_reason=REJECTION_REASON,
            matched_signals=signals,
            has_non_public_entry_path=False,
            public_social_actions_available=True,
            minimum_required_actions=actions_required,
            non_public_actions_available=0,
        )

    # Unknown-only: do not auto-reject.
    if unknown and n_public == 0:
        return EntryAcceptability(
            requires_public_social_action=False,
            entry_acceptable=True,
            entry_rejection_reason=None,
            matched_signals=(),
            has_non_public_entry_path=True,
            public_social_actions_available=False,
            minimum_required_actions=actions_required,
            non_public_actions_available=0,
        )
    if any_mandatory and n_public == 0 and n_non_public == 0:
        # Mandatory unknown actions only — leave to Gemini / text.
        return None
    return None


def assess_entry_acceptability(
    *,
    title: str | None = None,
    prize: str | None = None,
    body: str | None = None,
    entry_method: str | None = None,
    requirements: Sequence[str] | None = None,
    platform_actions: Iterable[Any] | None = None,
    actions_required: int | None = None,
) -> EntryAcceptability:
    """
    Prefer platform action metadata; fall back to conservative text heuristics.

    Accept when a non-public valid entry path exists.
    Reject only when every valid path requires a public social action.
    """
    if platform_actions is not None:
        plat = assess_platform_actions(
            platform_actions, actions_required=actions_required
        )
        if plat is not None:
            return plat

    parts = [p for p in (title, prize, body, entry_method) if p and str(p).strip()]
    if requirements:
        parts.extend(str(r) for r in requirements if r)
    blob_raw = "\n".join(parts)
    if not blob_raw.strip():
        return EntryAcceptability(
            requires_public_social_action=None,
            entry_acceptable=None,
            entry_rejection_reason=None,
        )

    blob = normalize_text(blob_raw)
    public_signals = _hits(blob, _PUBLIC_SOCIAL_PATTERNS)
    public_signals.extend(
        label
        for pattern, label in _PUBLIC_SOCIAL_PATTERNS
        if re.search(pattern, blob_raw, re.IGNORECASE) and label not in public_signals
    )
    non_public_signals = _hits(blob, _NON_PUBLIC_TEXT_PATTERNS)
    non_public_signals.extend(
        label
        for pattern, label in _NON_PUBLIC_TEXT_PATTERNS
        if re.search(pattern, blob_raw, re.IGNORECASE)
        and label not in non_public_signals
    )

    if not public_signals:
        return EntryAcceptability(
            requires_public_social_action=False,
            entry_acceptable=True,
            entry_rejection_reason=None,
            has_non_public_entry_path=True if non_public_signals else None,
            public_social_actions_available=False,
            non_public_actions_available=len(non_public_signals) or None,
        )

    # Public actions mentioned, but a non-public path is also described → accept.
    if non_public_signals and not _public_explicitly_mandatory_only(blob_raw):
        return EntryAcceptability(
            requires_public_social_action=False,
            entry_acceptable=True,
            entry_rejection_reason=None,
            matched_signals=tuple(dict.fromkeys(public_signals)),
            has_non_public_entry_path=True,
            public_social_actions_available=True,
            non_public_actions_available=len(non_public_signals),
        )

    if _looks_optional_only(blob_raw):
        return EntryAcceptability(
            requires_public_social_action=False,
            entry_acceptable=True,
            entry_rejection_reason=None,
            matched_signals=tuple(dict.fromkeys(public_signals)),
            has_non_public_entry_path=True,
            public_social_actions_available=True,
        )

    # Public action with mandatory framing and no clean non-public path.
    if _MANDATORY_MARKERS.search(blob_raw) or _public_explicitly_mandatory_only(
        blob_raw
    ):
        return EntryAcceptability(
            requires_public_social_action=True,
            entry_acceptable=False,
            entry_rejection_reason=REJECTION_REASON,
            matched_signals=tuple(dict.fromkeys(public_signals)),
            has_non_public_entry_path=False,
            public_social_actions_available=True,
        )

    # Ambiguous free text — do not auto-reject (Gemini may resolve).
    return EntryAcceptability(
        requires_public_social_action=None,
        entry_acceptable=None,
        entry_rejection_reason=None,
        matched_signals=tuple(dict.fromkeys(public_signals)),
        has_non_public_entry_path=None,
        public_social_actions_available=True,
    )


def _public_explicitly_mandatory_only(text: str) -> bool:
    """True when every public-action line carries mandatory markers and no optional."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    public_lines: list[str] = []
    for ln in lines:
        for pattern, _label in _PUBLIC_SOCIAL_PATTERNS:
            if re.search(pattern, ln, re.IGNORECASE):
                public_lines.append(ln)
                break
    if not public_lines:
        return bool(
            _MANDATORY_MARKERS.search(text) and not _OPTIONAL_MARKERS.search(text)
        )
    for ln in public_lines:
        if _OPTIONAL_MARKERS.search(ln):
            return False
        if not _MANDATORY_MARKERS.search(ln):
            return False
    return True


def _looks_optional_only(text: str) -> bool:
    """Public-action phrases appear only under optional/bonus wording."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    public_lines: list[str] = []
    for ln in lines:
        for pattern, _label in _PUBLIC_SOCIAL_PATTERNS:
            if re.search(pattern, ln, re.IGNORECASE):
                public_lines.append(ln)
                break
    if not public_lines:
        return bool(
            _OPTIONAL_MARKERS.search(text) and not _MANDATORY_MARKERS.search(text)
        )
    for ln in public_lines:
        if _MANDATORY_MARKERS.search(ln):
            return False
        if not _OPTIONAL_MARKERS.search(ln):
            return False
    return True


def merge_entry_acceptability(
    local: EntryAcceptability,
    *,
    gemini_requires_public: bool | None = None,
    gemini_acceptable: bool | None = None,
    gemini_reason: str | None = None,
) -> EntryAcceptability:
    """
    Prefer conclusive local platform-path decisions.

    Local accept with a known non-public path must not be overturned by Gemini
    merely noticing that public bonus actions exist.
    """
    if local.entry_acceptable is False:
        return local
    if local.entry_acceptable is True and local.has_non_public_entry_path is True:
        return EntryAcceptability(
            requires_public_social_action=False,
            entry_acceptable=True,
            entry_rejection_reason=None,
            matched_signals=local.matched_signals,
            has_non_public_entry_path=True,
            public_social_actions_available=local.public_social_actions_available,
            minimum_required_actions=local.minimum_required_actions,
            non_public_actions_available=local.non_public_actions_available,
        )
    if gemini_acceptable is False or gemini_requires_public is True:
        return EntryAcceptability(
            requires_public_social_action=True,
            entry_acceptable=False,
            entry_rejection_reason=gemini_reason or REJECTION_REASON,
            matched_signals=local.matched_signals,
            has_non_public_entry_path=False,
            public_social_actions_available=True,
            minimum_required_actions=local.minimum_required_actions,
            non_public_actions_available=local.non_public_actions_available,
        )
    if gemini_acceptable is True:
        return EntryAcceptability(
            requires_public_social_action=False,
            entry_acceptable=True,
            entry_rejection_reason=None,
            matched_signals=local.matched_signals,
            has_non_public_entry_path=True,
            public_social_actions_available=local.public_social_actions_available,
            minimum_required_actions=local.minimum_required_actions,
            non_public_actions_available=local.non_public_actions_available,
        )
    return local
