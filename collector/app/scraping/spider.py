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
        return assess_entry(
            title=title,
            body=excerpt,
            instructions=instructions,
            entry_method_text=instructions,
            restriction=restriction,
            purchase_required_text=meta.get("purchase_required_text")
            if isinstance(meta.get("purchase_required_text"), str)
            else None,
            free_hint=meta.get("free_hint") if isinstance(meta.get("free_hint"), bool) else None,
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
            identity = gleam_identity_from_url(entry_url)
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
            enrichment = self.adapter.enrich(response, page_url=page_url)
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
            yield response.follow(
                absolute,
                sid="http",
                callback=self.parse,
                meta={"depth": depth + 1, "anchor_text": (text or "")[:200]},
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
) -> GiveawayDiscoverySpider:
    """Build a configured spider instance for one source."""
    short = str(source_id).split("-")[0]
    attrs: dict[str, Any] = {
        "name": f"giveaway_{short}",
        "start_urls": [start_url],
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
    return items, stats
