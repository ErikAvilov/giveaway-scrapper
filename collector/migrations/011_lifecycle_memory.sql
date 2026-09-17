-- Long-term memory lifecycle: multi-source provenance + manual status timestamp.
-- Additive only. Does not purge or reset existing rows.

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS manual_status_updated_at TIMESTAMPTZ;

-- Backfill once from updated_at when a non-default manual status is already set.
UPDATE giveaways
SET manual_status_updated_at = COALESCE(manual_status_updated_at, updated_at)
WHERE manual_status IS DISTINCT FROM 'none'
  AND manual_status_updated_at IS NULL;

CREATE TABLE IF NOT EXISTS giveaway_sources (
    giveaway_id UUID NOT NULL REFERENCES giveaways (id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES sources (id) ON DELETE CASCADE,
    source_url TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (giveaway_id, source_id)
);

CREATE INDEX IF NOT EXISTS idx_giveaway_sources_source
    ON giveaway_sources (source_id, last_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_giveaway_sources_last_seen
    ON giveaway_sources (last_seen_at DESC);

-- Seed provenance from existing giveaways.source_id (best-effort, one row each).
INSERT INTO giveaway_sources (giveaway_id, source_id, source_url, first_seen_at, last_seen_at)
SELECT
    g.id,
    g.source_id,
    g.original_url,
    COALESCE(g.discovered_at, g.created_at, now()),
    COALESCE(g.last_seen_at, g.updated_at, now())
FROM giveaways g
WHERE g.source_id IS NOT NULL
ON CONFLICT (giveaway_id, source_id) DO NOTHING;

-- Inbox / actionable queue helper index.
CREATE INDEX IF NOT EXISTS idx_giveaways_inbox
    ON giveaways (discovered_at DESC)
    WHERE manual_status IN ('none', 'interested')
      AND wanted_prize IS TRUE
      AND (eligible_france IS TRUE OR france_eligibility = 'eligible')
      AND entry_acceptable IS TRUE
      AND status = 'active'
      AND (entry_url_status IS NULL OR entry_url_status <> 'gone');
