"""Candidate diagnostic helpers for dry-run / real-test output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.scraping.scoring import normalize_text

_NEGATIVE_PHRASES = (
    "concours cloture",
    "jeu cloture",
    "termine",
    "expire",
    "expired",
    "ended",
    "closed",
    "plus disponible",
    "resultats des gagnants",
    "gagnants du concours",
    "iexpired",
    "this competition has closed",
    "purchase required",
    "free spins",
    "no deposit",
)


@dataclass(slots=True)
class CandidateDiagnostics:
    score: float
    url: str
    source: str
    title: str | None
    positive_signals: list[str]
    negative_signals: list[str]
    would_analyze: bool
    entry_url: str | None = None
    prize: str | None = None
    restriction: str | None = None
    entry_method: str | None = None
    entry_friction: str | None = None
    free_entry: bool | None = None
    eligible_france: bool | None = None
    discovery_priority: int | None = None
    platform: str | None = None
    platform_campaign_id: str | None = None

    def format_lines(self) -> list[str]:
        lines = [
            f"source={self.source}",
            f'title={self.title!r}',
        ]
        if self.restriction is not None:
            lines.append(f"restriction={self.restriction!r}")
        if self.entry_method is not None:
            lines.append(f"entry_method={self.entry_method}")
        if self.entry_friction is not None:
            lines.append(f"entry_friction={self.entry_friction}")
        if self.free_entry is not None:
            lines.append(f"free={self.free_entry}")
        if self.eligible_france is not None:
            lines.append(f"eligible_france={self.eligible_france}")
        if self.platform:
            lines.append(f"platform={self.platform}")
        if self.platform_campaign_id:
            lines.append(f"platform_campaign_id={self.platform_campaign_id}")
        if self.entry_url:
            lines.append(f"entry_url={self.entry_url}")
        if self.prize:
            lines.append(f"prize={self.prize!r}")
        lines.append(f"score={self.score:.2f}")
        lines.append(f"would_analyze={self.would_analyze}")
        if self.discovery_priority is not None:
            lines.append(f"discovery_priority={self.discovery_priority}")
        lines.append(f"url={self.url}")
        lines.append(
            "  + "
            + (", ".join(self.positive_signals) if self.positive_signals else "(none)")
        )
        lines.append(
            "  - "
            + (", ".join(self.negative_signals) if self.negative_signals else "(none)")
        )
        return lines


def _positive_from_evidence(evidence: dict[str, Any] | None) -> list[str]:
    if not evidence:
        return []
    positives: list[str] = []
    flag_labels = (
        ("url_keyword", "url_keyword"),
        ("title_keyword", "title_keyword"),
        ("anchor_keyword", "anchor_keyword"),
        ("has_terms_link", "terms_link"),
        ("has_deadline_language", "deadline"),
        ("has_entry_language", "entry_language"),
    )
    for key, label in flag_labels:
        if evidence.get(key):
            positives.append(label)
    strong = int(evidence.get("content_strong_hits") or 0)
    if strong:
        positives.append(f"content_strong_hits={strong}")
    weak = int(evidence.get("content_weak_hits") or 0)
    if weak:
        positives.append(f"content_weak_hits={weak}")
    for term in list(evidence.get("matched_terms") or [])[:12]:
        positives.append(f"term:{term}")
    seen: set[str] = set()
    out: list[str] = []
    for item in positives:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _negative_signals(*, content: str, evidence: dict[str, Any] | None, meta: dict | None, item: dict[str, Any]) -> list[str]:
    negatives: list[str] = []
    blob = normalize_text(content or "")
    for phrase in _NEGATIVE_PHRASES:
        needle = normalize_text(phrase)
        if " " in needle:
            if needle in blob:
                negatives.append(f"phrase:{phrase}")
        elif re.search(rf"(?<![a-z0-9\-]){re.escape(needle)}(?![a-z0-9\-])", blob):
            negatives.append(f"phrase:{phrase}")
    if meta and meta.get("expired"):
        negatives.append("adapter:expired")
    for reason in list(item.get("skip_reasons") or [])[:8]:
        negatives.append(f"filter:{reason}")
    if evidence and not evidence.get("matched_terms") and not evidence.get("url_keyword"):
        negatives.append("weak_evidence")
    seen: set[str] = set()
    out: list[str] = []
    for entry in negatives:
        if entry not in seen:
            seen.add(entry)
            out.append(entry)
    return out[:12]


def build_candidate_diagnostics(
    item: dict[str, Any],
    *,
    source_name: str,
    threshold: float,
) -> CandidateDiagnostics:
    score = float(item.get("score") or 0.0)
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    content = str(item.get("raw_excerpt") or "")
    title = item.get("title")
    has_content = bool((title or content or "").strip())
    would_analyze = score >= threshold and has_content and not item.get("skip_analyze")
    meta = item.get("adapter_meta") if isinstance(item.get("adapter_meta"), dict) else None
    restriction = item.get("geo_restriction") or (meta or {}).get("restriction_text")
    return CandidateDiagnostics(
        score=score,
        url=str(item.get("url") or item.get("original_url") or ""),
        source=source_name,
        title=str(title) if title else None,
        positive_signals=_positive_from_evidence(evidence),
        negative_signals=_negative_signals(
            content=content,
            evidence=evidence,
            meta=meta,
            item=item,
        ),
        would_analyze=would_analyze,
        entry_url=str(item["entry_url"]) if item.get("entry_url") else None,
        prize=str(item["prize"]) if item.get("prize") else None,
        restriction=str(restriction) if restriction else None,
        entry_method=str(item["entry_method"]) if item.get("entry_method") else None,
        entry_friction=str(item["entry_friction"]) if item.get("entry_friction") else None,
        free_entry=item.get("free_entry") if isinstance(item.get("free_entry"), bool) else None,
        eligible_france=item.get("eligible_france")
        if isinstance(item.get("eligible_france"), bool)
        else None,
        discovery_priority=int(item["discovery_priority"])
        if item.get("discovery_priority") is not None
        else None,
        platform=str(item["platform"]) if item.get("platform") else None,
        platform_campaign_id=str(item["platform_campaign_id"])
        if item.get("platform_campaign_id")
        else None,
    )


def count_would_analyze(candidates: list[dict[str, Any]], *, threshold: float) -> int:
    return sum(
        1
        for item in candidates
        if build_candidate_diagnostics(item, source_name="", threshold=threshold).would_analyze
    )
