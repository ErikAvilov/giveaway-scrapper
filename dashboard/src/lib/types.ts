export type GiveawayStatus =
  | "candidate"
  | "active"
  | "expired"
  | "rejected"
  | "uncertain";

export type ManualStatus =
  | "none"
  | "interested"
  | "entered"
  | "ignored"
  | "won"
  | "lost";

export type SourceType =
  | "giveaway_aggregator"
  | "brand"
  | "blog"
  | "forum"
  | "other";

export type CrawlRunStatus = "running" | "success" | "partial" | "failed";

export type PrizeCategory =
  | "physical_good"
  | "cash"
  | "general_gift_card"
  | "restricted_gift_card"
  | "digital_game"
  | "digital_good"
  | "experience"
  | "travel"
  | "event_ticket"
  | "service"
  | "books_media"
  | "discount"
  | "subscription"
  | "other"
  | "unknown";

export interface GiveawayRow {
  id: string;
  canonical_url: string;
  original_url: string;
  source_id: string | null;
  source_name: string | null;
  domain: string;
  title: string | null;
  description: string | null;
  prize: string | null;
  prize_value_eur: number | null;
  prize_category: PrizeCategory | null;
  wanted_prize: boolean | null;
  prize_priority: number | null;
  preference_reason: string | null;
  requires_travel: boolean | null;
  requires_additional_spend: boolean | null;
  free_entry: boolean | null;
  eligible_france: boolean | null;
  france_eligibility: "eligible" | "ineligible" | "unknown" | null;
  eligibility_reason: string | null;
  entry_url_status: "live" | "gone" | "temporary_error" | "blocked" | "unknown" | null;
  entry_http_status: number | null;
  requires_purchase: boolean | null;
  requires_social: boolean | null;
  entry_method: string | null;
  start_at: Date | null;
  end_at: Date | null;
  terms_url: string | null;
  entry_url: string | null;
  status: GiveawayStatus;
  confidence: number | null;
  content_hash: string;
  discovered_at: Date;
  last_seen_at: Date;
  analyzed_at: Date | null;
  raw_excerpt: string | null;
  link_hints: string[];
  analysis_json: Record<string, unknown> | null;
  manual_status: ManualStatus;
  created_at: Date;
  updated_at: Date;
}

export interface SourceRow {
  id: string;
  name: string;
  base_url: string;
  source_type: SourceType;
  enabled: boolean;
  crawl_interval_minutes: number;
  last_crawled_at: Date | null;
  next_crawl_at: Date | null;
  crawl_config: Record<string, unknown>;
  created_at: Date;
  updated_at: Date;
}

export interface CrawlRunRow {
  id: string;
  source_id: string | null;
  source_name: string | null;
  started_at: Date;
  finished_at: Date | null;
  status: CrawlRunStatus;
  pages_fetched: number;
  candidates_found: number;
  giveaways_created: number;
  giveaways_updated: number;
  errors_count: number;
  error_summary: string | null;
  created_at: Date;
}

export interface OverviewStats {
  active: number;
  france_eligible: number;
  free_entry: number;
  ending_24h: number;
  ending_7d: number;
  discovered_today: number;
  entered: number;
  won: number;
  ignored: number;
}

export type GiveawaySort =
  | "newest"
  | "ending_soon"
  | "highest_value"
  | "highest_confidence"
  | "priority";

export interface GiveawayFilters {
  q?: string;
  status?: "active" | "expired" | "all";
  france?: boolean;
  free?: boolean;
  wanted_only?: boolean;
  hide_gone?: boolean;
  show_unknown_france?: boolean;
  show_ineligible?: boolean;
  show_unwanted?: boolean;
  prize_category?: PrizeCategory | "all";
  entry_method?: string;
  source_id?: string;
  manual_status?: ManualStatus | "all";
  ending_soon?: boolean;
  min_value?: number;
  sort?: GiveawaySort;
  limit?: number;
  offset?: number;
}
