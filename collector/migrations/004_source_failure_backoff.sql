-- Source crawl failure backoff (additive only).

ALTER TABLE sources
    ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER NOT NULL DEFAULT 0
        CHECK (consecutive_failures >= 0);

ALTER TABLE sources
    ADD COLUMN IF NOT EXISTS last_error_at TIMESTAMPTZ;
