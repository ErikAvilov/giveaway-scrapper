-- Platform identity for hosted giveaways (Gleam, etc.). Additive only.
-- Enables future cross-aggregator dedup without changing existing rows' meaning.

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS platform TEXT;

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS platform_campaign_id TEXT;

CREATE INDEX IF NOT EXISTS idx_giveaways_platform_campaign
    ON giveaways (platform, platform_campaign_id)
    WHERE platform IS NOT NULL AND platform_campaign_id IS NOT NULL;
