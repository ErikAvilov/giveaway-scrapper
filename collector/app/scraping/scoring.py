"""Lightweight heuristic scoring for giveaway page candidates."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field

from app.scraping.keywords import (
    DEADLINE_PHRASES,
    ENTRY_PHRASES,
    KEYWORDS_EN,
    KEYWORDS_FR,
    PHRASES_EN,
    PHRASES_FR,
    TERMS_LINK_HINTS,
    WEAK_KEYWORDS_EN,
)


def normalize_text(text: str) -> str:
    """Lowercase + strip accents for robust FR/EN matching."""
    lowered = text.lower()
    decomposed = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _word_boundary_pattern(token: str) -> re.Pattern[str]:
    """Match whole tokens; hyphens glue compounds (prize-ribbon ≠ prize)."""
    escaped = re.escape(token)
    return re.compile(rf"(?<![a-z0-9\-]){escaped}(?![a-z0-9\-])", re.IGNORECASE)


def _count_phrase_hits(haystack: str, phrases: tuple[str, ...]) -> int:
    hits = 0
    for phrase in phrases:
        needle = normalize_text(phrase)
        if " " in needle or "'" in needle:
            if needle in haystack:
                hits += 1
        elif _word_boundary_pattern(needle).search(haystack):
            hits += 1
    return hits


def _has_any(haystack: str, phrases: tuple[str, ...]) -> bool:
    return _count_phrase_hits(haystack, phrases) > 0


@dataclass(slots=True)
class CandidateEvidence:
    url_keyword: bool = False
    title_keyword: bool = False
    anchor_keyword: bool = False
    content_strong_hits: int = 0
    content_weak_hits: int = 0
    has_terms_link: bool = False
    has_deadline_language: bool = False
    has_entry_language: bool = False
    matched_terms: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CandidateScore:
    score: float
    evidence: CandidateEvidence

    @property
    def evidence_dict(self) -> dict[str, object]:
        return asdict(self.evidence)


def score_candidate(
    *,
    url: str,
    title: str = "",
    content: str = "",
    anchor_text: str = "",
    link_texts: list[str] | None = None,
) -> CandidateScore:
    """
    Score how likely a page is a giveaway/contest.

    A single weak keyword in body content is not enough — threshold is applied
    by the caller (default ~0.45).
    """
    url_n = normalize_text(url)
    title_n = normalize_text(title)
    content_n = normalize_text(content)
    anchor_n = normalize_text(anchor_text)
    links_blob = normalize_text(" ".join(link_texts or []))

    strong = PHRASES_FR + PHRASES_EN + KEYWORDS_FR + KEYWORDS_EN
    evidence = CandidateEvidence()
    matched: list[str] = []

    def _mark(flag_attr: str, phrases: tuple[str, ...], haystack: str) -> None:
        found = False
        for phrase in phrases:
            needle = normalize_text(phrase)
            ok = (
                needle in haystack
                if (" " in needle or "'" in needle)
                else bool(_word_boundary_pattern(needle).search(haystack))
            )
            if ok:
                found = True
                if phrase not in matched:
                    matched.append(phrase)
        if found:
            setattr(evidence, flag_attr, True)

    _mark("url_keyword", strong, url_n)
    _mark("title_keyword", strong, title_n)
    _mark("anchor_keyword", strong, anchor_n)

    evidence.content_strong_hits = _count_phrase_hits(content_n, strong)
    evidence.content_weak_hits = _count_phrase_hits(content_n, WEAK_KEYWORDS_EN)
    for phrase in strong:
        needle = normalize_text(phrase)
        hit = (
            needle in content_n
            if (" " in needle or "'" in needle)
            else bool(_word_boundary_pattern(needle).search(content_n))
        )
        if hit and phrase not in matched:
            matched.append(phrase)

    evidence.has_terms_link = _has_any(links_blob, TERMS_LINK_HINTS) or _has_any(
        content_n,
        ("reglement", "reglement du jeu", "official rules", "terms and conditions"),
    )
    evidence.has_deadline_language = _has_any(content_n, DEADLINE_PHRASES)
    evidence.has_entry_language = _has_any(content_n, ENTRY_PHRASES)
    evidence.matched_terms = matched[:20]

    score = 0.0
    if evidence.url_keyword:
        score += 0.30
    if evidence.title_keyword:
        score += 0.22
    if evidence.anchor_keyword:
        score += 0.10

    if evidence.content_strong_hits >= 3:
        score += 0.26
    elif evidence.content_strong_hits == 2:
        score += 0.14
    elif evidence.content_strong_hits == 1:
        score += 0.06

    if evidence.content_weak_hits and evidence.content_strong_hits == 0:
        score += min(0.05 * evidence.content_weak_hits, 0.08)
    elif evidence.content_weak_hits:
        score += min(0.02 * evidence.content_weak_hits, 0.05)

    if evidence.has_terms_link:
        score += 0.16
    if evidence.has_deadline_language:
        score += 0.14
    if evidence.has_entry_language:
        score += 0.14

    # Soft penalty: title/content keyword-only pages without URL or
    # participation/rules signals stay below the default threshold.
    structural = (
        evidence.url_keyword
        or evidence.has_terms_link
        or evidence.has_deadline_language
        or evidence.has_entry_language
    )
    if not structural and evidence.content_strong_hits < 3:
        score *= 0.85

    return CandidateScore(score=min(score, 1.0), evidence=evidence)
