-- Public social-action entry gate (hard preference, independent of prize).
-- Additive only.

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS requires_public_social_action BOOLEAN;

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS entry_acceptable BOOLEAN;

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS entry_rejection_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_giveaways_entry_acceptable
    ON giveaways (entry_acceptable);

CREATE INDEX IF NOT EXISTS idx_giveaways_public_social
    ON giveaways (requires_public_social_action)
    WHERE requires_public_social_action IS TRUE;

-- Main useful-queue index: France + wanted + acceptable + active + not gone.
CREATE INDEX IF NOT EXISTS idx_giveaways_main_queue_v2
    ON giveaways (wanted_prize, france_eligibility, entry_acceptable, status, prize_priority DESC NULLS LAST)
    WHERE wanted_prize IS TRUE
      AND france_eligibility = 'eligible'
      AND entry_acceptable IS TRUE
      AND status = 'active'
      AND (entry_url_status IS NULL OR entry_url_status <> 'gone');
