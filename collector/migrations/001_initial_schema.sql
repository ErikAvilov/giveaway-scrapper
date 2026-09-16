-- Initial schema for giveaway discovery (Neon PostgreSQL).
-- Safe to re-run: IF NOT EXISTS / guarded indexes only. Never drops data.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- sources: sites / feeds the crawler checks periodically
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    source_type TEXT NOT NULL
        CHECK (source_type IN (
            'giveaway_aggregator',
            'brand',
            'blog',
            'forum',
            'other'
        )),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    crawl_interval_minutes INTEGER NOT NULL DEFAULT 60
        CHECK (crawl_interval_minutes >= 5),
    last_crawled_at TIMESTAMPTZ,
    next_crawl_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sources_enabled_next_crawl
    ON sources (next_crawl_at)
    WHERE enabled = TRUE;

CREATE INDEX IF NOT EXISTS idx_sources_source_type
    ON sources (source_type);

-- ---------------------------------------------------------------------------
-- giveaways: discovered contests (deduped by canonical_url)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS giveaways (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_url TEXT NOT NULL,
    original_url TEXT NOT NULL,
    source_id UUID REFERENCES sources (id) ON DELETE SET NULL,
    domain TEXT NOT NULL,
    title TEXT,
    description TEXT,
    prize TEXT,
    prize_value_eur NUMERIC(12, 2),
    free_entry BOOLEAN,
    eligible_france BOOLEAN,
    requires_purchase BOOLEAN,
    requires_social BOOLEAN,
    entry_method TEXT,
    start_at TIMESTAMPTZ,
    end_at TIMESTAMPTZ,
    terms_url TEXT,
    entry_url TEXT,
    status TEXT NOT NULL DEFAULT 'candidate'
        CHECK (status IN (
            'candidate',
            'active',
            'expired',
            'rejected',
            'uncertain'
        )),
    confidence REAL
        CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    content_hash TEXT NOT NULL,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    analyzed_at TIMESTAMPTZ,
    raw_excerpt TEXT,
    analysis_json JSONB,
    manual_status TEXT NOT NULL DEFAULT 'none'
        CHECK (manual_status IN (
            'none',
            'interested',
            'entered',
            'ignored',
            'won',
            'lost'
        )),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT giveaways_canonical_url_key UNIQUE (canonical_url)
);

CREATE INDEX IF NOT EXISTS idx_giveaways_active
    ON giveaways (end_at)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_giveaways_end_at
    ON giveaways (end_at);

CREATE INDEX IF NOT EXISTS idx_giveaways_discovered_at
    ON giveaways (discovered_at DESC);

CREATE INDEX IF NOT EXISTS idx_giveaways_source_id
    ON giveaways (source_id);

CREATE INDEX IF NOT EXISTS idx_giveaways_domain
    ON giveaways (domain);

CREATE INDEX IF NOT EXISTS idx_giveaways_manual_status
    ON giveaways (manual_status);

CREATE INDEX IF NOT EXISTS idx_giveaways_eligible_france
    ON giveaways (eligible_france)
    WHERE eligible_france IS TRUE;

CREATE INDEX IF NOT EXISTS idx_giveaways_free_entry
    ON giveaways (free_entry)
    WHERE free_entry IS TRUE;

-- Rows waiting for (re)analysis after crawl or content change
CREATE INDEX IF NOT EXISTS idx_giveaways_needs_analysis
    ON giveaways (discovered_at)
    WHERE analyzed_at IS NULL;

-- ---------------------------------------------------------------------------
-- crawl_runs: crawler execution history
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crawl_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID REFERENCES sources (id) ON DELETE SET NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL
        CHECK (status IN (
            'running',
            'success',
            'partial',
            'failed'
        )),
    pages_fetched INTEGER NOT NULL DEFAULT 0,
    candidates_found INTEGER NOT NULL DEFAULT 0,
    giveaways_created INTEGER NOT NULL DEFAULT 0,
    giveaways_updated INTEGER NOT NULL DEFAULT 0,
    errors_count INTEGER NOT NULL DEFAULT 0,
    error_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_crawl_runs_source_id
    ON crawl_runs (source_id);

CREATE INDEX IF NOT EXISTS idx_crawl_runs_started_at
    ON crawl_runs (started_at DESC);
