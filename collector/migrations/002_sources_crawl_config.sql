-- Per-source crawl overrides (max_pages, max_depth, …). Additive only.

ALTER TABLE sources
    ADD COLUMN IF NOT EXISTS crawl_config JSONB NOT NULL DEFAULT '{}'::jsonb;
