"""Detect mandatory public social-media actions (hard entry gate).

Independent from prize preference and France eligibility.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from app.extraction.entry_assessment import normalize_text

REJECTION_REASON = "requires public social-media action"

# Mandatory public actions (EN + FR). Avoid bare "instagram"/"facebook".
_PUBLIC_SOCIAL_PATTERNS: tuple[tuple[str, str], ...] = (
    # Tag / mention friends
    (r"\btag\s+(?:a\s+)?(?:friend|friends|\d+\s+friends?)\b", "tag_friend"),
    (r"\btag\s+\d+\b", "tag_friend"),
    (r"\bmention\s+(?:a\s+)?(?:friend|friends|\d+\s+friends?)\b", "mention_friend"),
    (r"\bidentifi(?:ez|er)\s+(?:un\s+)?ami\b", "tag_friend_fr"),
    (r"\btagu(?:ez|er)\s+(?:un\s+)?ami\b", "tag_friend_fr"),
    (r"\bmentionn(?:ez|er)\s+(?:un\s+)?ami\b", "mention_friend_fr"),
    (r"\binvit(?:ez|er)\s+(?:des\s+)?amis?\s+publiquement\b", "invite_friends_fr"),
    # Comments
    (r"\bcomment\s+below\b", "comment"),
    (r"\bleave\s+a\s+comment\b", "comment"),
    (r"\bpost\s+a\s+comment\b", "comment"),
    (r"\bcomment\s+on\s+(?:this\s+)?(?:post|photo|video|reel)\b", "comment"),
    (r"\bcomment(?:ez|er)\b", "comment_fr"),
    (r"\blaissez?\s+un\s+commentaire\b", "comment_fr"),
    # Share / repost / retweet / story
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
    # Create public content
    (r"\bpost\s+(?:a\s+)?(?:photo|video|reel|story)\b", "post_content"),
    (r"\bpost\s+to\s+(?:instagram|facebook|tiktok|twitter|x)\b", "post_content"),
    (r"\bpublish\s+(?:a\s+)?(?:post|photo|video)\b", "post_content"),
    (r"\bcreate\s+(?:a\s+)?(?:post|story|video|ugc)\b", "ugc"),
    (r"\buser[- ]generated\s+content\b", "ugc"),
    (r"\bpubliez?\s+(?:une\s+)?(?:photo|vid[eé]o|publication)\b", "post_content_fr"),
    # Public hashtag / testimonial
    (r"\buse\s+(?:the\s+)?hashtag\b", "hashtag"),
    (r"\bpost\s+(?:with\s+)?#\w+", "hashtag"),
    (r"\butilisez?\s+(?:le\s+)?hashtag\b", "hashtag_fr"),
    (r"\bpublic\s+(?:testimonial|review)\b", "testimonial"),
    (r"\bpublic\s+referral\s+post\b", "referral_post"),
)

# Soft / non-disqualifying (follow alone, etc.) — used only to avoid false positives
# when optional bonus language surrounds a public action.
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

# Gleam / SweepWidget-style action types that are public when mandatory.
PUBLIC_SOCIAL_ACTION_TYPES: frozenset[str] = frozenset(
    {
        "twitter_retweet",
        "twitter_tweet",
        "twitter_hashtags",
        "twitter_comment",
        "twitter_reply",
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
    }
)

_PUBLIC_TYPE_SUBSTR = (
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
)


@dataclass(slots=True, frozen=True)
class EntryAcceptability:
    requires_public_social_action: bool | None
    entry_acceptable: bool | None
    entry_rejection_reason: str | None
    matched_signals: tuple[str, ...] = ()

    @property
    def skip_gemini(self) -> bool:
        """Clear local reject — no need to spend Gemini on social gate."""
        return self.entry_acceptable is False


def _hits(blob: str, patterns: Sequence[tuple[str, str]]) -> list[str]:
    found: list[str] = []
    for pattern, label in patterns:
        if re.search(pattern, blob, re.IGNORECASE):
            found.append(label)
    return found


def is_public_social_action_type(entry_type: str | None) -> bool:
    et = (entry_type or "").strip().lower()
    if not et:
        return False
    if et in PUBLIC_SOCIAL_ACTION_TYPES:
        return True
    return any(s in et for s in _PUBLIC_TYPE_SUBSTR)


def assess_platform_actions(
    actions: Iterable[Any],
) -> EntryAcceptability | None:
    """
    Inspect platform action objects (GleamEntryAction-like).

    Expects attributes: entry_type (str), mandatory (bool).
    Returns None when no conclusive mandatory public action is found.
    """
    matched: list[str] = []
    for action in actions:
        et = getattr(action, "entry_type", None) or (
            action.get("entry_type") if isinstance(action, dict) else None
        )
        mandatory = getattr(action, "mandatory", None)
        if mandatory is None and isinstance(action, dict):
            mandatory = action.get("mandatory")
        if mandatory is False:
            continue
        if is_public_social_action_type(str(et) if et else None):
            matched.append(str(et))
    if not matched:
        return None
    return EntryAcceptability(
        requires_public_social_action=True,
        entry_acceptable=False,
        entry_rejection_reason=REJECTION_REASON,
        matched_signals=tuple(dict.fromkeys(matched)),
    )


def assess_entry_acceptability(
    *,
    title: str | None = None,
    prize: str | None = None,
    body: str | None = None,
    entry_method: str | None = None,
    requirements: Sequence[str] | None = None,
    platform_actions: Iterable[Any] | None = None,
) -> EntryAcceptability:
    """
    Conservative local classification.

    - True reject when mandatory public social action is clear.
    - True accept when text is present and no public-social signal fires.
    - None/unknown when insufficient text.
    """
    if platform_actions is not None:
        plat = assess_platform_actions(platform_actions)
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
    signals = _hits(blob, _PUBLIC_SOCIAL_PATTERNS)
    # Also scan original (accents / hashtags)
    signals.extend(
        label
        for pattern, label in _PUBLIC_SOCIAL_PATTERNS
        if re.search(pattern, blob_raw, re.IGNORECASE) and label not in signals
    )

    if not signals:
        return EntryAcceptability(
            requires_public_social_action=False,
            entry_acceptable=True,
            entry_rejection_reason=None,
        )

    # If every hit sits only in an optional/bonus clause and no mandatory marker
    # near public actions, treat as optional (acceptable).
    if _looks_optional_only(blob_raw, signals):
        return EntryAcceptability(
            requires_public_social_action=False,
            entry_acceptable=True,
            entry_rejection_reason=None,
            matched_signals=tuple(dict.fromkeys(signals)),
        )

    return EntryAcceptability(
        requires_public_social_action=True,
        entry_acceptable=False,
        entry_rejection_reason=REJECTION_REASON,
        matched_signals=tuple(dict.fromkeys(signals)),
    )


def _looks_optional_only(text: str, _signals: list[str]) -> bool:
    """
    Heuristic: public-action phrases appear only under optional/bonus wording,
    and no mandatory marker accompanies them.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    public_lines: list[str] = []
    for ln in lines:
        for pattern, _label in _PUBLIC_SOCIAL_PATTERNS:
            if re.search(pattern, ln, re.IGNORECASE):
                public_lines.append(ln)
                break
    if not public_lines:
        # Single-paragraph blob
        return bool(
            _OPTIONAL_MARKERS.search(text) and not _MANDATORY_MARKERS.search(text)
        )

    for ln in public_lines:
        if _MANDATORY_MARKERS.search(ln):
            return False
        if not _OPTIONAL_MARKERS.search(ln):
            # Check nearby context (±1 line) in original
            return False
    return True


def merge_entry_acceptability(
    local: EntryAcceptability,
    *,
    gemini_requires_public: bool | None = None,
    gemini_acceptable: bool | None = None,
    gemini_reason: str | None = None,
) -> EntryAcceptability:
    """Prefer clear local reject; otherwise adopt Gemini when provided."""
    if local.entry_acceptable is False:
        return local
    if gemini_acceptable is False or gemini_requires_public is True:
        return EntryAcceptability(
            requires_public_social_action=True,
            entry_acceptable=False,
            entry_rejection_reason=gemini_reason or REJECTION_REASON,
            matched_signals=local.matched_signals,
        )
    if gemini_acceptable is True:
        return EntryAcceptability(
            requires_public_social_action=gemini_requires_public is True,
            entry_acceptable=True,
            entry_rejection_reason=None,
            matched_signals=local.matched_signals,
        )
    return local
