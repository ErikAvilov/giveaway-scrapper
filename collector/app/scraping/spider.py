"""Scrapling HTTP spider for bounded giveaway candidate discovery."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, ClassVar
from uuid import UUID

from scrapling.fetchers import FetcherSession
from scrapling.spiders import Request, Spider
from scrapling.spiders.session import SessionManager

from app.extraction.entry_acceptability import assess_entry_acceptability
from app.extraction.entry_assessment import (
    EntryAssessment,
    EntryFriction,
    assess_entry,
    discovery_priority,
)
from app.extraction.france_eligibility import (
    FranceEligibility,
    classify_france_eligibility,
)
from app.extraction.prize_preference import assess_prize_preference
from app.models.giveaway import GiveawayStatus
from app.platforms.gleam import gleam_identity_from_url
from app.platforms.sweepwidget import sweepwidget_identity_from_url
from app.scraping.adapters import get_adapter
from app.scraping.adapters.base import ChildCandidate, PageEnrichment, SourceAdapter
from app.scraping.filters import normalize_follow_url, should_follow_url
from app.scraping.scoring import score_candidate
from app.scraping.text_extract import (
    extract_anchors,
    extract_link_hints,
    extract_main_text,
    extract_title,
)
from app.urls import canonicalize_url

logger = logging.getLogger(__name__)

_BLOCKED_FOLLOW_MARKERS = (
    "/url/",
    "url.php",
    "/sweepstakes/",
    "countHits.pl",
    "link-track",
)


@dataclass(slots=True)
class SpiderLimits:
    max_depth: int
    max_pages: int
    candidate_threshold: float
    excerpt_max_chars: int
    request_timeout: float
    retries: int
    gleam_directory_max_pages: int = 5


class GiveawayDiscoverySpider(Spider):
    """HTTP-only spider. Class attributes are overridden per source via factory."""

    name = "giveaway_discovery"
    start_urls: ClassVar[list[str]] = []
    allowed_domains: ClassVar[set[str]] = set()

    robots_txt_obey = False
    concurrent_requests = 2
    concurrent_requests_per_domain = 1
    download_delay = 1.0
    max_blocked_retries = 2

    autothrottle_enabled = True
    autothrottle_start_delay = 1.0
    autothrottle_max_delay = 30.0

    logging_level = logging.INFO
    fp_keep_fragments = False

    # Instance state set by factory / __init__
    source_id: UUID | None = None
    limits: SpiderLimits | None = None
    base_domain: str = ""
    adapter: SourceAdapter | None = None
    source_name: str = ""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pages_fetched = 0
        self._seen_canonical: set[str] = set()
        self._candidate_urls: set[str] = set()
        self._errors: list[str] = []
        self._gleam_directory_stats: dict[str, Any] = {
            "listing_pages_fetched": 0,
            "directory_links_discovered": 0,
            "giveaway_detail_pages_scheduled": 0,
            "giveaway_detail_enqueued": 0,
            "giveaway_detail_pages_fetched": 0,
            "giveaway_detail_http_2xx": 0,
            "giveaway_detail_http_errors": 0,
            "classic_campaign_pages_fetched": 0,
            "classic_campaign_http_2xx": 0,
            "campaigns_parsed": 0,
            "campaign_parse_failures": 0,
            "duplicates": 0,
            "filtered_before_detail": 0,
            "filtered_after_detail": 0,
            "parse_failure_reasons": [],
            "sample_titles": [],
            "sample_detail_urls": [],
            "seen_campaign_ids": [],
        }

    def _gleam_bump(self, **deltas: Any) -> None:
        stats = self._gleam_directory_stats
        for key, value in deltas.items():
            if key in {
                "sample_titles",
                "sample_detail_urls",
                "parse_failure_reasons",
                "seen_campaign_ids",
            }:
                existing = list(stats.get(key) or [])
                items = value if isinstance(value, list) else [value]
                for item in items:
                    if item and item not in existing:
                        existing.append(item)
                limit = 50 if key == "seen_campaign_ids" else 20
                stats[key] = existing[:limit]
            else:
                stats[key] = int(stats.get(key) or 0) + int(value or 0)

    def _gleam_finalize_stats(self) -> dict[str, Any]:
        stats = dict(self._gleam_directory_stats)
        parsed = int(stats.get("campaigns_parsed") or 0)
        failures = int(stats.get("campaign_parse_failures") or 0)
        http_2xx = int(stats.get("giveaway_detail_http_2xx") or 0)
        discovered = int(stats.get("directory_links_discovered") or 0)
        enqueued = int(stats.get("giveaway_detail_enqueued") or 0)
        # Scheduled = actually enqueued under MAX_PAGES (not merely discovered).
        stats["giveaway_detail_pages_scheduled"] = enqueued
        # Discovered but never enqueued because the page budget was exhausted.
        stats["filtered_before_detail"] = max(0, discovered - enqueued)
        denom = http_2xx if http_2xx > 0 else (parsed + failures)
        rate = (parsed / denom) if denom else None
        stats["campaign_parse_rate"] = round(rate, 4) if rate is not None else None
        stats["campaign_parse_rate_pct"] = (
            f"{round(rate * 100)}%" if rate is not None else "n/a"
        )
        stats.pop("seen_campaign_ids", None)
        stats.pop("giveaway_detail_enqueued", None)
        return stats

    def _response_http_status(self, response: Any) -> int | None:
        for attr in ("status", "status_code", "statusCode"):
            raw = getattr(response, attr, None)
            if raw is None:
                continue
            try:
                return int(raw)
            except (TypeError, ValueError):
                continue
        return None

    def _record_gleam_funnel(
        self,
        response: Any,
        *,
        page_url: str,
        enrichment: PageEnrichment,
    ) -> None:
        from app.platforms.gleam import (
            parse_gleam_campaign_url,
            parse_gleam_directory_detail_url,
        )

        meta = enrichment.meta or {}
        status = self._response_http_status(response)
        ok = status is None or 200 <= status < 300

        if meta.get("gleam_directory_listing"):
            discovered = int(meta.get("giveaway_links_discovered") or 0)
            self._gleam_bump(
                listing_pages_fetched=1,
                directory_links_discovered=discovered,
                sample_titles=list(meta.get("sample_titles") or []),
                sample_detail_urls=list(meta.get("sample_detail_urls") or []),
            )
            return

        if meta.get("gleam_directory_detail") or parse_gleam_directory_detail_url(
            page_url
        ):
            # Shell page — still counted, but not a campaign parse attempt.
            self._gleam_bump(directory_shell_pages_fetched=1)
            if not ok:
                self._gleam_bump(giveaway_detail_http_errors=1)
            return

        key, _slug = parse_gleam_campaign_url(page_url)
        if meta.get("gleam_classic_campaign") or key:
            # Classic campaign pages are the parse targets for this funnel.
            self._gleam_bump(
                giveaway_detail_pages_fetched=1,
                classic_campaign_pages_fetched=1,
            )
            if ok:
                self._gleam_bump(
                    giveaway_detail_http_2xx=1,
                    classic_campaign_http_2xx=1,
                )
            else:
                self._gleam_bump(giveaway_detail_http_errors=1)
                return
            if meta.get("parse_status") == "ok":
                cid = meta.get("platform_campaign_id") or key
                seen = list(self._gleam_directory_stats.get("seen_campaign_ids") or [])
                if cid and cid in seen:
                    self._gleam_bump(duplicates=1)
                else:
                    if cid:
                        self._gleam_bump(seen_campaign_ids=[cid])
                    self._gleam_bump(campaigns_parsed=1)
            elif meta.get("parse_status") == "payload_missing":
                reason = meta.get("parse_failure_reason") or "other"
                self._gleam_bump(
                    campaign_parse_failures=1,
                    parse_failure_reasons=[f"{reason}"],
                )

    def configure_sessions(self, manager: SessionManager) -> None:
        limits = self.limits
        timeout = limits.request_timeout if limits else 20.0
        retries = limits.retries if limits else 2
        # Explicit HTTP session only — never Playwright/Chromium.
        manager.add(
            "http",
            FetcherSession(
                impersonate="chrome",
                timeout=timeout,
                retries=retries,
                retry_delay=1,
                stealthy_headers=True,
            ),
        )

    async def start_requests(self) -> AsyncGenerator[Request, None]:
        if not self.start_urls:
            raise RuntimeError("Spider has no start_urls")
        for url in self.start_urls:
            yield Request(
                url,
                sid="http",
                callback=self.parse,
                meta={"depth": 0, "anchor_text": ""},
            )

    def _safe_extract(self, response: Any, limits: SpiderLimits) -> tuple[str, str, list[str]]:
        """Title/excerpt/links; tolerate RSS/XML and odd content types."""
        title = ""
        excerpt = ""
        link_texts: list[str] = []
        try:
            title = extract_title(response) or ""
        except (TypeError, ValueError, AttributeError):
            logger.debug("extract_title failed url=%s", getattr(response, "url", ""), exc_info=True)
        try:
            excerpt = extract_main_text(response, max_chars=limits.excerpt_max_chars) or ""
        except (TypeError, ValueError, AttributeError):
            logger.debug("extract_main_text failed url=%s", getattr(response, "url", ""), exc_info=True)
        try:
            link_texts = extract_link_hints(response)
        except (TypeError, ValueError, AttributeError):
            link_texts = []
        return title, excerpt, link_texts

    def _assessment_for(
        self,
        *,
        title: str | None,
        excerpt: str | None,
        enrichment: PageEnrichment | None,
        child: ChildCandidate | None = None,
    ) -> EntryAssessment:
        meta = dict((enrichment.meta if enrichment else {}) or {})
        if child:
            meta = {**meta, **(child.meta or {})}
        restriction = (
            (child.restriction_text if child else None)
            or (enrichment.restriction_text if enrichment else None)
        )
        instructions = (
            (child.entry_method_text if child else None)
            or (enrichment.entry_method_text if enrichment else None)
        )
        filter_body = (
            meta.get("filter_text")
            if isinstance(meta.get("filter_text"), str) and meta.get("filter_text").strip()
            else excerpt
        )
        return assess_entry(
            title=title,
            body=filter_body,
            instructions=instructions,
            entry_method_text=instructions,
            restriction=restriction,
            purchase_required_text=meta.get("purchase_required_text")
            if isinstance(meta.get("purchase_required_text"), str)
            else None,
            free_hint=meta.get("free_hint") if isinstance(meta.get("free_hint"), bool) else None,
            prize=(child.prize if child and child.prize else None)
            or (enrichment.prize if enrichment else None),
            category=meta.get("category") if isinstance(meta.get("category"), str) else None,
        )

    def _candidate_item(
        self,
        *,
        page_url: str,
        original_url: str,
        title: str | None,
        prize: str | None,
        excerpt: str | None,
        link_texts: list[str],
        entry_url: str | None,
        terms_url: str | None,
        depth: int,
        score: float,
        evidence: dict[str, object],
        assessment: EntryAssessment,
        adapter_meta: dict[str, Any],
        expired_flag: bool = False,
    ) -> dict[str, Any]:
        meta = dict(adapter_meta)
        if expired_flag:
            meta["expired"] = True

        friction = assessment.entry_friction
        override = meta.get("entry_friction_override")
        if isinstance(override, str):
            try:
                friction = EntryFriction(override)
            except ValueError:
                pass

        platform = meta.get("platform") if isinstance(meta.get("platform"), str) else None
        platform_campaign_id = (
            meta.get("platform_campaign_id")
            if isinstance(meta.get("platform_campaign_id"), str)
            else None
        )
        if entry_url:
            identity = gleam_identity_from_url(entry_url) or sweepwidget_identity_from_url(
                entry_url
            )
            if identity:
                platform = platform or identity.get("platform")
                platform_campaign_id = platform_campaign_id or identity.get(
                    "platform_campaign_id"
                )
                meta.setdefault("platform", platform)
                meta.setdefault("platform_campaign_id", platform_campaign_id)

        # Recompute discovery priority if Gleam overrode friction.
        priority = assessment.discovery_priority
        if friction is not assessment.entry_friction:
            priority = discovery_priority(
                free_entry=assessment.free_entry,
                friction=friction,
                eligible_france=assessment.eligible_france,
                geo_scope=assessment.geo_scope,
            )

        skip_analyze = bool(assessment.skip_gemini or expired_flag or meta.get("expired"))
        status = GiveawayStatus.CANDIDATE
        if skip_analyze and assessment.skip_reasons:
            status = GiveawayStatus.REJECTED
        elif expired_flag or meta.get("expired"):
            status = GiveawayStatus.EXPIRED
            skip_analyze = True

        pref = assess_prize_preference(title=title, prize=prize, body=excerpt)
        geo = assessment.geo_restriction
        fr = classify_france_eligibility(
            title=title,
            prize=prize,
            body=excerpt,
            restriction=geo,
        )
        eligible_france = fr.eligible_france
        france_eligibility = fr.france_eligibility.value
        eligibility_reason = fr.reason
        skip_reasons = list(assessment.skip_reasons)
        if fr.france_eligibility == FranceEligibility.INELIGIBLE:
            status = GiveawayStatus.REJECTED
            skip_analyze = True
            if eligibility_reason and eligibility_reason not in skip_reasons:
                skip_reasons.append(eligibility_reason)

        actions_for_gate: list[Any] = []
        mand = meta.get("mandatory_actions")
        opt = meta.get("optional_actions")
        if isinstance(mand, list):
            actions_for_gate.extend(mand)
        if isinstance(opt, list):
            actions_for_gate.extend(opt)
        if not actions_for_gate:
            for et in meta.get("mandatory_entry_types") or []:
                actions_for_gate.append({"entry_type": et, "mandatory": True})
            for et in meta.get("optional_entry_types") or []:
                actions_for_gate.append({"entry_type": et, "mandatory": False})

        actions_required_raw = meta.get("actions_required")
        actions_required: int | None = None
        if actions_required_raw is not None:
            try:
                actions_required = max(0, int(actions_required_raw))
            except (TypeError, ValueError):
                actions_required = None

        entry_gate = assess_entry_acceptability(
            title=title,
            prize=prize,
            body=excerpt,
            entry_method=assessment.entry_method,
            platform_actions=actions_for_gate or None,
            actions_required=actions_required,
        )
        if entry_gate.entry_acceptable is False:
            status = GiveawayStatus.REJECTED
            skip_analyze = True
            reason = entry_gate.entry_rejection_reason or "requires public social-media action"
            if reason not in skip_reasons:
                skip_reasons.append(reason)

        if (
            skip_analyze
            and meta.get("gleam_classic_campaign")
            and meta.get("parse_status") == "ok"
        ):
            self._gleam_bump(filtered_after_detail=1)

        return {
            "kind": "candidate",
            "url": page_url,
            "original_url": original_url,
            "title": title or None,
            "prize": prize,
            "raw_excerpt": excerpt or None,
            "link_hints": link_texts[:40],
            "entry_url": entry_url,
            "terms_url": terms_url,
            "score": score,
            "evidence": evidence,
            "adapter_meta": meta,
            "source_id": str(self.source_id) if self.source_id else None,
            "source_name": self.source_name,
            "depth": depth,
            "entry_friction": friction.value,
            "entry_method": assessment.entry_method or ("gleam" if platform == "gleam" else None),
            "free_entry": assessment.free_entry,
            "eligible_france": eligible_france,
            "france_eligibility": france_eligibility,
            "eligibility_reason": eligibility_reason,
            "requires_purchase": assessment.requires_purchase,
            "requires_social": assessment.requires_social,
            "geo_restriction": assessment.geo_restriction,
            "geo_scope": assessment.geo_scope.value,
            "discovery_priority": priority,
            "prize_category": pref.prize_category.value,
            "wanted_prize": pref.wanted_prize,
            "prize_priority": pref.prize_priority,
            "preference_reason": pref.preference_reason,
            "requires_travel": pref.requires_travel,
            "requires_additional_spend": pref.requires_additional_spend,
            "requires_public_social_action": entry_gate.requires_public_social_action,
            "entry_acceptable": entry_gate.entry_acceptable,
            "entry_rejection_reason": entry_gate.entry_rejection_reason,
            "platform": platform,
            "platform_campaign_id": platform_campaign_id,
            "skip_analyze": skip_analyze,
            "skip_reasons": skip_reasons,
            "status": str(status),
        }

    async def parse(self, response: Any) -> AsyncGenerator[dict[str, Any] | Request | None, None]:
        limits = self.limits
        if limits is None:
            return

        if self._pages_fetched >= limits.max_pages:
            return

        self._pages_fetched += 1
        depth = int((response.meta or {}).get("depth", 0))
        anchor_text = str((response.meta or {}).get("anchor_text", "") or "")

        try:
            page_url = canonicalize_url(response.url)
        except ValueError:
            page_url = response.url

        if page_url in self._seen_canonical:
            return
        self._seen_canonical.add(page_url)

        title, excerpt, link_texts = self._safe_extract(response, limits)
        entry_url: str | None = None
        terms_url: str | None = None
        prize: str | None = None
        skip_as_candidate = False
        adapter_follow: list[str] | None = None
        adapter_meta: dict[str, Any] = {}
        enrichment: PageEnrichment | None = None

        if self.adapter is not None:
            # Gleam directory pagination bound (Pi-friendly).
            if self.limits is not None:
                try:
                    response._gleam_directory_max_pages = self.limits.gleam_directory_max_pages
                except (AttributeError, TypeError):
                    pass
            enrichment = self.adapter.enrich(response, page_url=page_url)
            self._record_gleam_funnel(response, page_url=page_url, enrichment=enrichment)
            if enrichment.title:
                title = enrichment.title
            if enrichment.excerpt:
                excerpt = enrichment.excerpt
            if enrichment.prize:
                prize = enrichment.prize
            if enrichment.entry_url:
                entry_url = enrichment.entry_url
            if enrichment.terms_url:
                terms_url = enrichment.terms_url
            skip_as_candidate = enrichment.skip_as_candidate
            adapter_follow = enrichment.follow_urls
            adapter_meta = dict(enrichment.meta or {})
            if enrichment.organizer:
                adapter_meta["organizer"] = enrichment.organizer
            if enrichment.end_date_text:
                adapter_meta["end_date_text"] = enrichment.end_date_text
            if enrichment.restriction_text:
                adapter_meta["restriction_text"] = enrichment.restriction_text
            if enrichment.entry_method_text:
                adapter_meta["entry_method_text"] = enrichment.entry_method_text

            # Listing cards → multiple candidates (ContestGirl).
            for child in enrichment.child_candidates or []:
                try:
                    child_url = canonicalize_url(child.canonical_url)
                except ValueError:
                    child_url = child.canonical_url
                if child_url in self._candidate_urls:
                    continue
                child_title = child.title or title
                child_excerpt = child.excerpt or excerpt
                scored_child = score_candidate(
                    url=child_url,
                    title=child_title or "",
                    # Include title in body so listing cards clear the threshold.
                    content=f"{child_title or ''}\n{child_excerpt or ''}".strip(),
                    anchor_text=anchor_text,
                    link_texts=link_texts,
                )
                if scored_child.score < limits.candidate_threshold:
                    continue
                self._candidate_urls.add(child_url)
                assessment = self._assessment_for(
                    title=child_title,
                    excerpt=child_excerpt,
                    enrichment=enrichment,
                    child=child,
                )
                child_meta = {
                    **adapter_meta,
                    **(child.meta or {}),
                    "from_listing": page_url,
                }
                yield self._candidate_item(
                    page_url=child_url,
                    original_url=response.url,
                    title=child_title,
                    prize=child.prize or prize,
                    excerpt=child_excerpt,
                    link_texts=link_texts,
                    entry_url=child.entry_url,
                    terms_url=child.terms_url or terms_url,
                    depth=depth,
                    score=scored_child.score,
                    evidence=scored_child.evidence_dict,
                    assessment=assessment,
                    adapter_meta=child_meta,
                )

        scored = score_candidate(
            url=page_url,
            title=title,
            content=excerpt,
            anchor_text=anchor_text,
            link_texts=link_texts,
        )

        if (
            not skip_as_candidate
            and scored.score >= limits.candidate_threshold
            and page_url not in self._candidate_urls
        ):
            self._candidate_urls.add(page_url)
            assessment = self._assessment_for(
                title=title,
                excerpt=excerpt,
                enrichment=enrichment,
            )
            yield self._candidate_item(
                page_url=page_url,
                original_url=response.url,
                title=title or None,
                prize=prize,
                excerpt=excerpt or None,
                link_texts=link_texts,
                entry_url=entry_url,
                terms_url=terms_url,
                depth=depth,
                score=scored.score,
                evidence=scored.evidence_dict,
                assessment=assessment,
                adapter_meta=adapter_meta,
                expired_flag=bool(adapter_meta.get("expired")),
            )
        elif (
            not skip_as_candidate
            and adapter_meta.get("gleam_classic_campaign")
            and adapter_meta.get("parse_status") == "ok"
            and scored.score < limits.candidate_threshold
        ):
            self._gleam_bump(filtered_after_detail=1)

        if depth >= limits.max_depth:
            return
        if self._pages_fetched >= limits.max_pages:
            return

        from app.scraping.crawl_logic import can_go_deeper, should_enqueue_canonical

        if not can_go_deeper(depth, limits.max_depth):
            return

        allowed = set(self.allowed_domains) if self.allowed_domains else {self.base_domain}
        queued = set(self._seen_canonical)

        follow_pairs: list[tuple[str, str]]
        if adapter_follow is not None:
            follow_pairs = [(url, "") for url in adapter_follow]
        else:
            follow_pairs = []
            try:
                follow_pairs = [
                    (
                        (response.urljoin(href) if hasattr(response, "urljoin") else href),
                        text,
                    )
                    for href, text in extract_anchors(response)
                ]
            except (TypeError, ValueError, AttributeError):
                follow_pairs = []

        for absolute, text in follow_pairs:
            if not should_follow_url(
                absolute,
                allowed_domains=allowed,
                base_domain=self.base_domain,
            ):
                continue
            # Never fetch aggregator outbound redirectors that robots disallow.
            if any(marker in absolute for marker in _BLOCKED_FOLLOW_MARKERS):
                continue
            canonical = normalize_follow_url(absolute)
            if canonical is None:
                continue
            if not should_enqueue_canonical(
                canonical,
                seen=self._seen_canonical,
                queued=queued,
                max_pages=limits.max_pages,
                pages_fetched=self._pages_fetched,
            ):
                continue
            queued.add(canonical)
            from app.platforms.gleam import parse_gleam_campaign_url

            if (
                enrichment is not None
                and (enrichment.meta or {}).get("gleam_directory_listing")
                and parse_gleam_campaign_url(canonical)[0]
            ):
                self._gleam_bump(giveaway_detail_enqueued=1)
            yield response.follow(
                absolute,
                sid="http",
                callback=self.parse,
                meta={
                    "depth": depth + 1,
                    "anchor_text": (text or "")[:200],
                    "gleam_from_directory": bool(
                        enrichment is not None
                        and (enrichment.meta or {}).get("gleam_directory_listing")
                    ),
                },
            )


def build_spider(
    *,
    source_id: UUID,
    start_url: str,
    allowed_domain: str,
    concurrent_requests: int,
    concurrent_requests_per_domain: int,
    download_delay: float,
    autothrottle: bool,
    autothrottle_start_delay: float,
    autothrottle_max_delay: float,
    limits: SpiderLimits,
    adapter_key: str | None = None,
    source_name: str = "",
    extra_start_urls: list[str] | None = None,
) -> GiveawayDiscoverySpider:
    """Build a configured spider instance for one source."""
    short = str(source_id).split("-")[0]
    starts = [start_url]
    for extra in extra_start_urls or []:
        u = str(extra).strip()
        if u and u not in starts:
            starts.append(u)
    attrs: dict[str, Any] = {
        "name": f"giveaway_{short}",
        "start_urls": starts,
        "allowed_domains": {allowed_domain},
        "robots_txt_obey": False,
        "concurrent_requests": concurrent_requests,
        "concurrent_requests_per_domain": concurrent_requests_per_domain,
        "download_delay": download_delay,
        "max_blocked_retries": limits.retries,
        "autothrottle_enabled": autothrottle,
        "autothrottle_start_delay": autothrottle_start_delay,
        "autothrottle_max_delay": autothrottle_max_delay,
        "logging_level": logging.INFO,
    }
    cls = type(f"GiveawaySpider_{short}", (GiveawayDiscoverySpider,), attrs)
    spider: GiveawayDiscoverySpider = cls()
    spider.source_id = source_id
    spider.limits = limits
    spider.base_domain = allowed_domain
    resolved_adapter = adapter_key
    if not resolved_adapter and allowed_domain.removeprefix("www.") == "gleam.io":
        resolved_adapter = "gleam"
    spider.adapter = get_adapter(resolved_adapter)
    spider.source_name = source_name
    return spider


def run_spider(spider: GiveawayDiscoverySpider) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run spider synchronously; return candidate items + stats dict."""
    result = spider.start(use_uvloop=False)
    items = [item for item in result.items if isinstance(item, dict) and item.get("kind") == "candidate"]
    stats = result.stats.to_dict() if hasattr(result.stats, "to_dict") else {}
    stats["pages_fetched_local"] = spider._pages_fetched
    stats["candidates_local"] = len(items)
    stats["errors_local"] = list(spider._errors)
    stats["request_failed_count"] = stats.get("failed_requests_count", 0)
    if spider._gleam_directory_stats:
        stats["gleam_directory"] = spider._gleam_finalize_stats()
    return items, stats
