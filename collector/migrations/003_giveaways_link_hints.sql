-- Store crawl-time link hints for Gemini context. Additive only.

ALTER TABLE giveaways
    ADD COLUMN IF NOT EXISTS link_hints JSONB NOT NULL DEFAULT '[]'::jsonb;
