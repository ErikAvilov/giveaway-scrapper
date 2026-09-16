-- Manual revisit reminders (dashboard).
-- Additive only; never overwritten by crawl upserts.

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS remind_at TIMESTAMPTZ;

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS reminder_hours INTEGER
        CHECK (
            reminder_hours IS NULL
            OR (reminder_hours > 0 AND reminder_hours <= 24 * 30)
        );

CREATE INDEX IF NOT EXISTS idx_giveaways_remind_at
    ON giveaways (remind_at)
    WHERE remind_at IS NOT NULL;
