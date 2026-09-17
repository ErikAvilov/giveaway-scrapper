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


@dataclass(slots=True)
class SourceFilterSummary:
    source: str
    pages_fetched: int
    candidates: int
    france_eligible: int
    france_ineligible: int
    france_unknown: int
    wanted: int
    unwanted: int
    dead_urls: int
    duplicates: int
    would_keep: int
    public_social_required: int = 0
    campaigns_parsed: int = 0
    gleam_directory: dict[str, Any] | None = None

    def format_lines(self) -> list[str]:
        lines = [
            self.source,
            f"Fetched: {self.pages_fetched}",
            f"Candidates: {self.candidates}",
        ]
        gd = self.gleam_directory or {}
        if gd:
            rate = gd.get("campaign_parse_rate_pct") or "n/a"
            lines.extend(
                [
                    "Gleam Official Directory",
                    f"listing_pages_fetched={gd.get('listing_pages_fetched', 0)}",
                    f"directory_links_discovered={gd.get('directory_links_discovered', gd.get('giveaway_links_discovered', 0))}",
                    f"giveaway_detail_pages_scheduled={gd.get('giveaway_detail_pages_scheduled', 0)}",
                    f"giveaway_detail_pages_fetched={gd.get('giveaway_detail_pages_fetched', gd.get('detail_pages_fetched', 0))}",
                    f"giveaway_detail_http_2xx={gd.get('giveaway_detail_http_2xx', 0)}",
                    f"giveaway_detail_http_errors={gd.get('giveaway_detail_http_errors', 0)}",
                    f"campaigns_parsed={gd.get('campaigns_parsed', self.campaigns_parsed)}",
                    f"campaign_parse_failures={gd.get('campaign_parse_failures', 0)}",
                    f"campaign_parse_rate={rate}",
                    f"duplicates={gd.get('duplicates', self.duplicates)}",
                    f"filtered_before_detail={gd.get('filtered_before_detail', 0)}",
                    f"filtered_after_detail={gd.get('filtered_after_detail', 0)}",
                    f"france_eligible={self.france_eligible}",
                    f"france_ineligible={self.france_ineligible}",
                    f"france_unknown={self.france_unknown}",
                    f"wanted={self.wanted}",
                    f"unwanted={self.unwanted}",
                    f"public_social_required={self.public_social_required}",
                    f"would_keep={self.would_keep}",
                ]
            )
            for reason in gd.get("parse_failure_reasons") or []:
                lines.append(f"parse_failure={reason}")
            return lines
        lines.extend(
            [
                f"Worldwide/France: {self.france_eligible}",
                f"France ineligible: {self.france_ineligible}",
                f"France unknown: {self.france_unknown}",
                f"Wanted prizes: {self.wanted}",
                f"Unwanted: {self.unwanted}",
                f"public_social_required={self.public_social_required}",
                f"Dead: {self.dead_urls}",
                f"Duplicates: {self.duplicates}",
                f"Would keep: {self.would_keep}",
            ]
        )
        return lines


def summarize_source_candidates(
    *,
    source_name: str,
    pages_fetched: int,
    candidates: list[dict[str, Any]],
    threshold: float,
    gleam_directory: dict[str, Any] | None = None,
) -> SourceFilterSummary:
    """Aggregate France / prize / keep stats for real-test dry output."""
    fr_ok = fr_no = fr_unk = 0
    wanted = unwanted = 0
    dead = 0
    public_social = 0
    campaigns_parsed = 0
    seen_keys: set[str] = set()
    duplicates = 0
    would_keep = 0

    for item in candidates:
        fe = item.get("france_eligibility")
        if fe == "eligible" or item.get("eligible_france") is True:
            fr_ok += 1
        elif fe == "ineligible" or item.get("eligible_france") is False:
            fr_no += 1
        else:
            fr_unk += 1

        if item.get("wanted_prize") is True:
            wanted += 1
        elif item.get("wanted_prize") is False:
            unwanted += 1

        if item.get("entry_acceptable") is False or item.get(
            "requires_public_social_action"
        ) is True:
            public_social += 1

        if item.get("platform") == "gleam" and item.get("platform_campaign_id"):
            campaigns_parsed += 1

        status = str(item.get("entry_url_status") or "")
        if status == "gone":
            dead += 1

        key = None
        if item.get("platform") and item.get("platform_campaign_id"):
            key = f"{item['platform']}:{item['platform_campaign_id']}"
        elif item.get("entry_url"):
            key = f"entry:{item['entry_url']}"
        elif item.get("url"):
            key = f"url:{item['url']}"
        if key:
            if key in seen_keys:
                duplicates += 1
            else:
                seen_keys.add(key)

        diag = build_candidate_diagnostics(
            item, source_name=source_name, threshold=threshold
        )
        keep = (
            diag.would_analyze
            and (fe == "eligible" or item.get("eligible_france") is True)
            and item.get("wanted_prize") is not False
            and item.get("entry_acceptable") is not False
            and status != "gone"
            and str(item.get("status") or "") not in {"rejected", "expired"}
        )
        if keep:
            would_keep += 1

    return SourceFilterSummary(
        source=source_name,
        pages_fetched=pages_fetched,
        candidates=len(candidates),
        france_eligible=fr_ok,
        france_ineligible=fr_no,
        france_unknown=fr_unk,
        wanted=wanted,
        unwanted=unwanted,
        dead_urls=dead,
        duplicates=duplicates,
        would_keep=would_keep,
        public_social_required=public_social,
        campaigns_parsed=campaigns_parsed,
        gleam_directory=gleam_directory,
    )
