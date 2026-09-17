"""Ad-hoc URL probe — crawl one URL with optional config, no DB writes by default."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from psycopg import Connection

from app.config import Settings
from app.models.source import Source, SourceType
from app.scraping.adapters import get_adapter, registered_adapter_keys
from app.scraping.diagnostics import (
    build_candidate_diagnostics,
    count_would_analyze,
    summarize_source_candidates,
)
from app.scraping.runner import SourceCrawlResult, crawl_source
from app.urls import domain_from_url


@dataclass(slots=True)
class ProbeConfig:
    adapter: str | None = None
    max_pages: int = 8
    max_depth: int = 1
    candidate_threshold: float | None = None
    request_timeout: float | None = None
    retries: int | None = None
    extra_start_urls: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProbeResult:
    url: str
    source_name: str
    adapter: str | None
    crawl: SourceCrawlResult
    summary_lines: list[str]
    candidate_lines: list[str]
    payload: dict[str, Any]


def normalize_probe_url(raw: str) -> str:
    """Accept bare domains like example.com and turn them into https URLs."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("URL is empty")
    if "://" not in text:
        text = f"https://{text}"
    # Ensure trailing path for bare hosts (Scrapling / urlparse friendly).
    if text.count("/") == 2:  # scheme://host
        text = f"{text}/"
    return text


def build_probe_config(
    *,
    adapter: str | None = None,
    max_pages: int = 8,
    max_depth: int = 1,
    candidate_threshold: float | None = None,
    request_timeout: float | None = None,
    retries: int | None = None,
    extra_start_urls: list[str] | None = None,
    config_json: dict[str, Any] | None = None,
) -> ProbeConfig:
    raw = dict(config_json or {})
    resolved_adapter = adapter or raw.get("adapter")
    if resolved_adapter is not None:
        resolved_adapter = str(resolved_adapter).strip() or None
    if resolved_adapter and get_adapter(resolved_adapter) is None:
        known = ", ".join(registered_adapter_keys())
        raise ValueError(f"Unknown adapter {resolved_adapter!r}. Known: {known}")

    pages = int(raw.get("max_pages", max_pages))
    depth = int(raw.get("max_depth", max_depth))
    threshold = raw.get("candidate_threshold", candidate_threshold)
    timeout = raw.get("request_timeout", request_timeout)
    retry = raw.get("retries", retries)
    extras = extra_start_urls if extra_start_urls is not None else raw.get("extra_start_urls")
    if extras is None:
        extras = []
    if not isinstance(extras, list):
        raise TypeError("extra_start_urls must be a list")

    cfg = ProbeConfig(
        adapter=resolved_adapter,
        max_pages=max(1, pages),
        max_depth=max(0, depth),
        candidate_threshold=float(threshold) if threshold is not None else None,
        request_timeout=float(timeout) if timeout is not None else None,
        retries=int(retry) if retry is not None else None,
        extra_start_urls=[str(u) for u in extras],
        raw=raw,
    )
    return cfg


def ephemeral_source(url: str, cfg: ProbeConfig) -> Source:
    host = domain_from_url(url)
    crawl_config: dict[str, Any] = {
        "profile": "probe",
        "max_pages": cfg.max_pages,
        "max_depth": cfg.max_depth,
        **{k: v for k, v in cfg.raw.items() if k not in {"adapter", "extra_start_urls"}},
    }
    crawl_config["max_pages"] = cfg.max_pages
    crawl_config["max_depth"] = cfg.max_depth
    if cfg.adapter:
        crawl_config["adapter"] = cfg.adapter
    if cfg.candidate_threshold is not None:
        crawl_config["candidate_threshold"] = cfg.candidate_threshold
    if cfg.request_timeout is not None:
        crawl_config["request_timeout"] = cfg.request_timeout
    if cfg.retries is not None:
        crawl_config["retries"] = cfg.retries
    if cfg.extra_start_urls:
        crawl_config["extra_start_urls"] = list(cfg.extra_start_urls)

    return Source(
        id=uuid4(),
        name=f"probe:{host}",
        base_url=url,
        source_type=SourceType.OTHER,
        enabled=True,
        crawl_interval_minutes=60,
        crawl_config=crawl_config,
    )


def probe_url(
    conn: Connection,
    settings: Settings,
    url: str,
    *,
    adapter: str | None = None,
    max_pages: int = 8,
    max_depth: int = 1,
    candidate_threshold: float | None = None,
    request_timeout: float | None = None,
    retries: int | None = None,
    extra_start_urls: list[str] | None = None,
    config_json: dict[str, Any] | None = None,
) -> ProbeResult:
    """
    Crawl one URL with optional adapter/limits and return diagnostics.

    Always dry-run: never writes giveaways / crawl_runs (ephemeral source).
    """
    normalized = normalize_probe_url(url)
    cfg = build_probe_config(
        adapter=adapter,
        max_pages=max_pages,
        max_depth=max_depth,
        candidate_threshold=candidate_threshold,
        request_timeout=request_timeout,
        retries=retries,
        extra_start_urls=extra_start_urls,
        config_json=config_json,
    )
    source = ephemeral_source(normalized, cfg)
    crawl = crawl_source(
        conn,
        settings,
        source,
        dry_run=True,
        real_test=False,
    )

    threshold = crawl.candidate_threshold
    summary = summarize_source_candidates(
        source_name=crawl.source_name,
        pages_fetched=crawl.pages_fetched,
        candidates=crawl.candidates,
        threshold=threshold,
        gleam_directory=crawl.gleam_directory or None,
    )
    would = count_would_analyze(crawl.candidates, threshold=threshold)

    summary_lines = [
        f"url={normalized}",
        f"source={crawl.source_name}",
        f"adapter={cfg.adapter or '(none — generic spider)'}",
        f"max_pages={cfg.max_pages} max_depth={cfg.max_depth}",
        f"status={crawl.status}",
        f"pages_fetched={crawl.pages_fetched}",
        f"candidates={crawl.candidates_found}",
        f"would_analyze={would}",
        f"france_eligible={summary.france_eligible}",
        f"france_ineligible={summary.france_ineligible}",
        f"france_unknown={summary.france_unknown}",
        f"wanted={summary.wanted}",
        f"unwanted={summary.unwanted}",
        f"public_social_required={summary.public_social_required}",
        f"errors={crawl.errors_count}",
    ]
    gd = crawl.gleam_directory or {}
    if gd:
        rate = gd.get("campaign_parse_rate_pct") or "n/a"
        summary_lines.extend(
            [
                "Gleam Official Directory",
                f"listing_pages_fetched={gd.get('listing_pages_fetched', 0)}",
                f"directory_links_discovered={gd.get('directory_links_discovered', gd.get('giveaway_links_discovered', 0))}",
                f"giveaway_detail_pages_scheduled={gd.get('giveaway_detail_pages_scheduled', 0)}",
                f"giveaway_detail_pages_fetched={gd.get('giveaway_detail_pages_fetched', gd.get('detail_pages_fetched', 0))}",
                f"giveaway_detail_http_2xx={gd.get('giveaway_detail_http_2xx', 0)}",
                f"giveaway_detail_http_errors={gd.get('giveaway_detail_http_errors', 0)}",
                f"campaigns_parsed={gd.get('campaigns_parsed', summary.campaigns_parsed)}",
                f"campaign_parse_failures={gd.get('campaign_parse_failures', 0)}",
                f"campaign_parse_rate={rate}",
                f"duplicates={gd.get('duplicates', summary.duplicates)}",
                f"filtered_before_detail={gd.get('filtered_before_detail', 0)}",
                f"filtered_after_detail={gd.get('filtered_after_detail', 0)}",
                f"would_keep={summary.would_keep}",
            ]
        )
        for reason in gd.get("parse_failure_reasons") or []:
            summary_lines.append(f"parse_failure={reason}")
        samples = gd.get("sample_titles") or []
        sample_urls = gd.get("sample_detail_urls") or []
        if samples:
            summary_lines.append("sample_titles=" + " | ".join(str(t) for t in samples[:10]))
        if sample_urls:
            summary_lines.append(
                "sample_detail_urls=" + " | ".join(str(u) for u in sample_urls[:10])
            )
    if crawl.error_summary:
        summary_lines.append(f"error_summary={crawl.error_summary}")

    candidate_lines: list[str] = []
    diag_payloads: list[dict[str, Any]] = []
    for item in crawl.candidates:
        diag = build_candidate_diagnostics(
            item,
            source_name=crawl.source_name,
            threshold=threshold,
        )
        candidate_lines.extend(diag.format_lines())
        candidate_lines.append("---")
        diag_payloads.append(
            {
                "title": diag.title,
                "url": diag.url,
                "score": diag.score,
                "would_analyze": diag.would_analyze,
                "prize": diag.prize,
                "entry_url": diag.entry_url,
                "restriction": diag.restriction,
                "entry_method": diag.entry_method,
                "entry_friction": diag.entry_friction,
                "free_entry": diag.free_entry,
                "eligible_france": diag.eligible_france,
                "platform": diag.platform,
                "platform_campaign_id": diag.platform_campaign_id,
                "positive_signals": diag.positive_signals,
                "negative_signals": diag.negative_signals,
                "wanted_prize": item.get("wanted_prize"),
                "entry_acceptable": item.get("entry_acceptable"),
                "france_eligibility": item.get("france_eligibility"),
                "status": item.get("status"),
            }
        )

    payload = {
        "url": normalized,
        "adapter": cfg.adapter,
        "config": source.crawl_config,
        "status": str(crawl.status),
        "pages_fetched": crawl.pages_fetched,
        "candidates_found": crawl.candidates_found,
        "would_analyze": would,
        "errors_count": crawl.errors_count,
        "error_summary": crawl.error_summary,
        "france_eligible": summary.france_eligible,
        "france_ineligible": summary.france_ineligible,
        "france_unknown": summary.france_unknown,
        "wanted": summary.wanted,
        "unwanted": summary.unwanted,
        "public_social_required": summary.public_social_required,
        "gleam_directory": crawl.gleam_directory or {},
        "candidates": diag_payloads,
    }
    return ProbeResult(
        url=normalized,
        source_name=crawl.source_name,
        adapter=cfg.adapter,
        crawl=crawl,
        summary_lines=summary_lines,
        candidate_lines=candidate_lines,
        payload=payload,
    )
