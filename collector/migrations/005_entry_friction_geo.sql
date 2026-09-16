-- Additive discovery metadata for entry friction and geographic restriction text.
-- Never drops or rewrites existing columns/data.

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS entry_friction TEXT
        CHECK (
            entry_friction IS NULL
            OR entry_friction IN ('easy', 'medium', 'hard', 'unknown')
        );

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS geo_restriction TEXT;

CREATE INDEX IF NOT EXISTS idx_giveaways_entry_friction
    ON giveaways (entry_friction)
    WHERE entry_friction IS NOT NULL;
