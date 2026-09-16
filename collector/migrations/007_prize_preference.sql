-- Prize preference / prioritization for economic-value filtering.
-- Additive only — does not drop or rewrite existing columns/data.

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS prize_category TEXT
        CHECK (
            prize_category IS NULL
            OR prize_category IN (
                'physical_good',
                'cash',
                'general_gift_card',
                'restricted_gift_card',
                'digital_game',
                'digital_good',
                'experience',
                'travel',
                'event_ticket',
                'service',
                'books_media',
                'discount',
                'subscription',
                'other',
                'unknown'
            )
        );

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS wanted_prize BOOLEAN;

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS prize_priority INTEGER
        CHECK (
            prize_priority IS NULL
            OR (prize_priority >= 0 AND prize_priority <= 100)
        );

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS preference_reason TEXT;

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS requires_travel BOOLEAN;

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS requires_additional_spend BOOLEAN;

CREATE INDEX IF NOT EXISTS idx_giveaways_wanted_priority
    ON giveaways (wanted_prize, prize_priority DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_giveaways_prize_category
    ON giveaways (prize_category)
    WHERE prize_category IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_giveaways_needs_analysis_preference
    ON giveaways (wanted_prize, prize_priority DESC NULLS LAST, discovered_at)
    WHERE analyzed_at IS NULL AND status = 'candidate';
