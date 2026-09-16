-- France-first eligibility + entry URL validation diagnostics.
-- Additive only.

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS france_eligibility TEXT
        CHECK (
            france_eligibility IS NULL
            OR france_eligibility IN ('eligible', 'ineligible', 'unknown')
        );

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS eligibility_reason TEXT;

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS eligible_countries JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS excluded_countries JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS entry_http_status INTEGER;

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS entry_checked_at TIMESTAMPTZ;

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS entry_url_status TEXT
        CHECK (
            entry_url_status IS NULL
            OR entry_url_status IN (
                'live',
                'gone',
                'temporary_error',
                'blocked',
                'unknown'
            )
        );

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS entry_fail_count INTEGER NOT NULL DEFAULT 0;

-- Backfill france_eligibility from existing eligible_france when unset.
UPDATE giveaways
SET france_eligibility = CASE
    WHEN eligible_france IS TRUE THEN 'eligible'
    WHEN eligible_france IS FALSE THEN 'ineligible'
    ELSE 'unknown'
END
WHERE france_eligibility IS NULL;

CREATE INDEX IF NOT EXISTS idx_giveaways_france_eligibility
    ON giveaways (france_eligibility);

CREATE INDEX IF NOT EXISTS idx_giveaways_entry_url_status
    ON giveaways (entry_url_status)
    WHERE entry_url_status IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_giveaways_main_queue
    ON giveaways (wanted_prize, france_eligibility, status, prize_priority DESC NULLS LAST)
    WHERE wanted_prize IS TRUE
      AND france_eligibility = 'eligible'
      AND status = 'active'
      AND (entry_url_status IS NULL OR entry_url_status <> 'gone');
