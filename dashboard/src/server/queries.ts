import "server-only";

import { sql } from "@/lib/db";
import type {
  CrawlRunRow,
  GiveawayFilters,
  GiveawayRow,
  ManualStatus,
  OverviewStats,
  SourceRow,
} from "@/lib/types";

function mapGiveaway(row: Record<string, unknown>): GiveawayRow {
  const hints = row.link_hints;
  let link_hints: string[] = [];
  if (Array.isArray(hints)) link_hints = hints.map(String);
  else if (typeof hints === "string") {
    try {
      const parsed = JSON.parse(hints);
      if (Array.isArray(parsed)) link_hints = parsed.map(String);
    } catch {
      link_hints = [];
    }
  }

  return {
    id: String(row.id),
    canonical_url: String(row.canonical_url),
    original_url: String(row.original_url),
    source_id: row.source_id ? String(row.source_id) : null,
    source_name: row.source_name ? String(row.source_name) : null,
    domain: String(row.domain),
    title: row.title != null ? String(row.title) : null,
    description: row.description != null ? String(row.description) : null,
    prize: row.prize != null ? String(row.prize) : null,
    prize_value_eur:
      row.prize_value_eur != null && row.prize_value_eur !== ""
        ? Number(row.prize_value_eur)
        : null,
    prize_category: (row.prize_category as GiveawayRow["prize_category"]) ?? null,
    wanted_prize: row.wanted_prize as boolean | null,
    prize_priority: row.prize_priority != null ? Number(row.prize_priority) : null,
    preference_reason:
      row.preference_reason != null ? String(row.preference_reason) : null,
    requires_travel: row.requires_travel as boolean | null,
    requires_additional_spend: row.requires_additional_spend as boolean | null,
    free_entry: row.free_entry as boolean | null,
    eligible_france: row.eligible_france as boolean | null,
    france_eligibility:
      (row.france_eligibility as GiveawayRow["france_eligibility"]) ?? null,
    eligibility_reason:
      row.eligibility_reason != null ? String(row.eligibility_reason) : null,
    entry_url_status:
      (row.entry_url_status as GiveawayRow["entry_url_status"]) ?? null,
    entry_http_status:
      row.entry_http_status != null ? Number(row.entry_http_status) : null,
    requires_purchase: row.requires_purchase as boolean | null,
    requires_social: row.requires_social as boolean | null,
    requires_public_social_action: row.requires_public_social_action as boolean | null,
    entry_acceptable: row.entry_acceptable as boolean | null,
    entry_rejection_reason:
      row.entry_rejection_reason != null ? String(row.entry_rejection_reason) : null,
    entry_method: row.entry_method != null ? String(row.entry_method) : null,
    start_at: row.start_at ? new Date(String(row.start_at)) : null,
    end_at: row.end_at ? new Date(String(row.end_at)) : null,
    terms_url: row.terms_url != null ? String(row.terms_url) : null,
    entry_url: row.entry_url != null ? String(row.entry_url) : null,
    status: row.status as GiveawayRow["status"],
    confidence: row.confidence != null ? Number(row.confidence) : null,
    content_hash: String(row.content_hash),
    discovered_at: new Date(String(row.discovered_at)),
    last_seen_at: new Date(String(row.last_seen_at)),
    analyzed_at: row.analyzed_at ? new Date(String(row.analyzed_at)) : null,
    raw_excerpt: row.raw_excerpt != null ? String(row.raw_excerpt) : null,
    link_hints,
    analysis_json: (row.analysis_json as Record<string, unknown> | null) ?? null,
    manual_status: row.manual_status as ManualStatus,
    remind_at: row.remind_at ? new Date(String(row.remind_at)) : null,
    reminder_hours: row.reminder_hours != null ? Number(row.reminder_hours) : null,
    reminder_due: Boolean(row.reminder_due),
    created_at: new Date(String(row.created_at)),
    updated_at: new Date(String(row.updated_at)),
  };
}

export async function getOverviewStats(): Promise<OverviewStats> {
  const rows = await sql`
    SELECT
      (SELECT count(*)::int FROM giveaways WHERE status = 'active' AND manual_status <> 'ignored') AS active,
      (SELECT count(*)::int FROM giveaways WHERE eligible_france IS TRUE AND manual_status <> 'ignored') AS france_eligible,
      (SELECT count(*)::int FROM giveaways WHERE free_entry IS TRUE AND manual_status <> 'ignored') AS free_entry,
      (SELECT count(*)::int FROM giveaways
        WHERE status = 'active'
          AND manual_status <> 'ignored'
          AND end_at IS NOT NULL
          AND end_at <= now() + interval '24 hours'
          AND end_at >= now()) AS ending_24h,
      (SELECT count(*)::int FROM giveaways
        WHERE status = 'active'
          AND manual_status <> 'ignored'
          AND end_at IS NOT NULL
          AND end_at <= now() + interval '7 days'
          AND end_at >= now()) AS ending_7d,
      (SELECT count(*)::int FROM giveaways
        WHERE discovered_at >= date_trunc('day', now() AT TIME ZONE 'UTC')
          AND manual_status <> 'ignored') AS discovered_today,
      (SELECT count(*)::int FROM giveaways
        WHERE remind_at IS NOT NULL
          AND remind_at <= now()
          AND manual_status <> 'ignored') AS reminders_due,
      (SELECT count(*)::int FROM giveaways WHERE manual_status = 'entered') AS entered,
      (SELECT count(*)::int FROM giveaways WHERE manual_status = 'won') AS won,
      (SELECT count(*)::int FROM giveaways WHERE manual_status = 'ignored') AS ignored
  `;
  const r = rows[0] as Record<string, number>;
  return {
    active: Number(r.active),
    france_eligible: Number(r.france_eligible),
    free_entry: Number(r.free_entry),
    ending_24h: Number(r.ending_24h),
    ending_7d: Number(r.ending_7d),
    discovered_today: Number(r.discovered_today),
    reminders_due: Number(r.reminders_due),
    entered: Number(r.entered),
    won: Number(r.won),
    ignored: Number(r.ignored),
  };
}

export async function listRecentGiveaways(limit = 8): Promise<GiveawayRow[]> {
  const rows = await sql`
    SELECT g.*, s.name AS source_name,
           (g.remind_at IS NOT NULL AND g.remind_at <= now()) AS reminder_due
    FROM giveaways g
    LEFT JOIN sources s ON s.id = g.source_id
    WHERE g.manual_status <> 'ignored'
    ORDER BY g.discovered_at DESC
    LIMIT ${limit}
  `;
  return rows.map((r) => mapGiveaway(r as Record<string, unknown>));
}

export async function listEndingSoon(limit = 8): Promise<GiveawayRow[]> {
  const rows = await sql`
    SELECT g.*, s.name AS source_name,
           (g.remind_at IS NOT NULL AND g.remind_at <= now()) AS reminder_due
    FROM giveaways g
    LEFT JOIN sources s ON s.id = g.source_id
    WHERE g.end_at IS NOT NULL
      AND g.end_at >= now()
      AND g.status IN ('active', 'candidate', 'uncertain')
      AND g.manual_status <> 'ignored'
    ORDER BY g.end_at ASC
    LIMIT ${limit}
  `;
  return rows.map((r) => mapGiveaway(r as Record<string, unknown>));
}

export async function countIgnoredGiveaways(): Promise<number> {
  const rows = await sql`
    SELECT count(*)::int AS n FROM giveaways WHERE manual_status = 'ignored'
  `;
  return Number((rows[0] as { n: number }).n);
}

export async function listGiveaways(
  filters: GiveawayFilters = {},
): Promise<{ rows: GiveawayRow[]; total: number }> {
  const status = filters.status ?? "all";
  const sort = filters.sort ?? "priority";
  const limit = Math.min(Math.max(filters.limit ?? 50, 1), 200);
  const offset = Math.max(filters.offset ?? 0, 0);
  const q = filters.q?.trim() || null;
  const qPattern = q ? `%${q}%` : null;
  const france = filters.france === true ? true : null;
  const free = filters.free === true ? true : null;
  const wantedOnly = filters.wanted_only === true ? true : null;
  const hideGone = filters.hide_gone !== false;
  const showUnknownFrance = filters.show_unknown_france === true;
  const showIneligible = filters.show_ineligible === true;
  const showUnwanted = filters.show_unwanted === true;
  const acceptableOnly = filters.acceptable_only !== false;
  const publicSocialRequired = filters.public_social_required === true ? true : null;
  const entryRejectionReason = filters.entry_rejection_reason?.trim() || null;
  const endingSoon = filters.ending_soon === true ? true : null;
  const remindersDue = filters.reminders_due === true ? true : null;
  const hasReminder = filters.has_reminder === true ? true : null;
  const entryMethod = filters.entry_method || null;
  const prizeCategory =
    filters.prize_category && filters.prize_category !== "all"
      ? filters.prize_category
      : null;
  const sourceId = filters.source_id || null;
  const manualStatusRaw = filters.manual_status ?? "all";
  const manualStatus =
    manualStatusRaw && manualStatusRaw !== "all" ? manualStatusRaw : null;
  // Default main view hides ignored; opening manual_status=ignored shows the ignore list.
  const hideIgnored = manualStatus !== "ignored";
  const minValue = filters.min_value ?? null;

  // Default main queue: France eligible only (unless inspecting unknown/ineligible).
  const franceEligibleOnly =
    france === true && !showUnknownFrance && !showIneligible;

  const orderSql =
    sort === "ending_soon"
      ? sql`g.end_at ASC NULLS LAST`
      : sort === "remind_at"
        ? sql`g.remind_at ASC NULLS LAST`
        : sort === "highest_value"
          ? sql`g.prize_value_eur DESC NULLS LAST, g.discovered_at DESC`
          : sort === "highest_confidence"
            ? sql`g.confidence DESC NULLS LAST, g.discovered_at DESC`
            : sort === "newest"
              ? sql`g.discovered_at DESC`
              : sql`CASE WHEN g.wanted_prize IS TRUE THEN 0 WHEN g.wanted_prize IS NULL THEN 1 ELSE 2 END, g.prize_priority DESC NULLS LAST, g.discovered_at DESC`;

  const rows = await sql`
    SELECT g.*, s.name AS source_name,
           (g.remind_at IS NOT NULL AND g.remind_at <= now()) AS reminder_due,
           count(*) OVER()::int AS _total
    FROM giveaways g
    LEFT JOIN sources s ON s.id = g.source_id
    WHERE 1=1
      AND (
        ${status} = 'all'
        OR (${status} = 'active' AND g.status = 'active')
        OR (${status} = 'expired' AND g.status = 'expired')
      )
      AND (
        ${franceEligibleOnly}::boolean IS NOT TRUE
        OR g.eligible_france IS TRUE
        OR g.france_eligibility = 'eligible'
      )
      AND (
        ${showUnknownFrance}::boolean IS NOT TRUE
        OR g.france_eligibility = 'unknown'
        OR (g.france_eligibility IS NULL AND g.eligible_france IS NULL)
      )
      AND (
        ${showIneligible}::boolean IS NOT TRUE
        OR g.france_eligibility = 'ineligible'
        OR g.eligible_france IS FALSE
      )
      AND (${free}::boolean IS NULL OR g.free_entry IS TRUE)
      AND (
        ${wantedOnly}::boolean IS NULL
        OR ${showUnwanted}::boolean IS TRUE
        OR g.wanted_prize IS TRUE
      )
      AND (
        ${showUnwanted}::boolean IS NOT TRUE
        OR g.wanted_prize IS FALSE
      )
      AND (
        ${acceptableOnly}::boolean IS FALSE
        OR g.entry_acceptable IS DISTINCT FROM FALSE
      )
      AND (
        ${publicSocialRequired}::boolean IS NULL
        OR g.requires_public_social_action IS TRUE
      )
      AND (
        ${entryRejectionReason}::text IS NULL
        OR g.entry_rejection_reason ILIKE ${entryRejectionReason}
      )
      AND (
        ${hideGone}::boolean IS FALSE
        OR g.entry_url_status IS NULL
        OR g.entry_url_status <> 'gone'
      )
      AND (${prizeCategory}::text IS NULL OR g.prize_category = ${prizeCategory})
      AND (${entryMethod}::text IS NULL OR g.entry_method = ${entryMethod})
      AND (${sourceId}::uuid IS NULL OR g.source_id = ${sourceId}::uuid)
      AND (${manualStatus}::text IS NULL OR g.manual_status = ${manualStatus})
      AND (${hideIgnored}::boolean IS FALSE OR g.manual_status <> 'ignored')
      AND (
        ${endingSoon}::boolean IS NULL
        OR (
          g.end_at IS NOT NULL
          AND g.end_at >= now()
          AND g.end_at <= now() + interval '7 days'
        )
      )
      AND (
        ${remindersDue}::boolean IS NULL
        OR (g.remind_at IS NOT NULL AND g.remind_at <= now())
      )
      AND (
        ${hasReminder}::boolean IS NULL
        OR g.remind_at IS NOT NULL
      )
      AND (${minValue}::numeric IS NULL OR g.prize_value_eur >= ${minValue})
      AND (
        ${qPattern}::text IS NULL
        OR g.title ILIKE ${qPattern}
        OR g.prize ILIKE ${qPattern}
        OR g.domain ILIKE ${qPattern}
        OR g.canonical_url ILIKE ${qPattern}
      )
    ORDER BY ${orderSql}
    LIMIT ${limit}
    OFFSET ${offset}
  `;

  const total = rows.length ? Number((rows[0] as { _total: number })._total) : 0;
  return {
    total,
    rows: rows.map((r) => mapGiveaway(r as Record<string, unknown>)),
  };
}

export async function getGiveaway(id: string): Promise<GiveawayRow | null> {
  const rows = await sql`
    SELECT g.*, s.name AS source_name,
           (g.remind_at IS NOT NULL AND g.remind_at <= now()) AS reminder_due
    FROM giveaways g
    LEFT JOIN sources s ON s.id = g.source_id
    WHERE g.id = ${id}::uuid
    LIMIT 1
  `;
  if (!rows.length) return null;
  return mapGiveaway(rows[0] as Record<string, unknown>);
}

export async function updateManualStatus(
  id: string,
  manualStatus: ManualStatus,
): Promise<GiveawayRow | null> {
  const allowed: ManualStatus[] = [
    "none",
    "interested",
    "entered",
    "ignored",
    "won",
    "lost",
  ];
  if (!allowed.includes(manualStatus)) {
    throw new Error("Invalid manual_status");
  }
  const rows = await sql`
    UPDATE giveaways
    SET manual_status = ${manualStatus},
        updated_at = now()
    WHERE id = ${id}::uuid
    RETURNING *,
      (SELECT name FROM sources WHERE id = giveaways.source_id) AS source_name,
      (remind_at IS NOT NULL AND remind_at <= now()) AS reminder_due
  `;
  if (!rows.length) return null;
  return mapGiveaway(rows[0] as Record<string, unknown>);
}

const REMINDER_HOURS_MIN = 1;
const REMINDER_HOURS_MAX = 24 * 30;

export async function setGiveawayReminder(
  id: string,
  hours: number,
): Promise<GiveawayRow | null> {
  const h = Math.trunc(Number(hours));
  if (!Number.isFinite(h) || h < REMINDER_HOURS_MIN || h > REMINDER_HOURS_MAX) {
    throw new Error(`Reminder hours must be between ${REMINDER_HOURS_MIN} and ${REMINDER_HOURS_MAX}`);
  }
  const rows = await sql`
    UPDATE giveaways
    SET remind_at = now() + (${h} * interval '1 hour'),
        reminder_hours = ${h},
        updated_at = now()
    WHERE id = ${id}::uuid
    RETURNING *,
      (SELECT name FROM sources WHERE id = giveaways.source_id) AS source_name,
      (remind_at IS NOT NULL AND remind_at <= now()) AS reminder_due
  `;
  if (!rows.length) return null;
  return mapGiveaway(rows[0] as Record<string, unknown>);
}

export async function clearGiveawayReminder(
  id: string,
): Promise<GiveawayRow | null> {
  const rows = await sql`
    UPDATE giveaways
    SET remind_at = NULL,
        reminder_hours = NULL,
        updated_at = now()
    WHERE id = ${id}::uuid
    RETURNING *,
      (SELECT name FROM sources WHERE id = giveaways.source_id) AS source_name,
      false AS reminder_due
  `;
  if (!rows.length) return null;
  return mapGiveaway(rows[0] as Record<string, unknown>);
}

export async function countRemindersDue(): Promise<number> {
  const rows = await sql`
    SELECT count(*)::int AS n
    FROM giveaways
    WHERE remind_at IS NOT NULL
      AND remind_at <= now()
      AND manual_status <> 'ignored'
  `;
  return Number((rows[0] as { n: number }).n);
}

export async function listSources(): Promise<SourceRow[]> {
  const rows = await sql`
    SELECT * FROM sources
    ORDER BY enabled DESC, name ASC
  `;
  return rows.map((row) => ({
    id: String(row.id),
    name: String(row.name),
    base_url: String(row.base_url),
    source_type: row.source_type as SourceRow["source_type"],
    enabled: Boolean(row.enabled),
    crawl_interval_minutes: Number(row.crawl_interval_minutes),
    last_crawled_at: row.last_crawled_at ? new Date(String(row.last_crawled_at)) : null,
    next_crawl_at: row.next_crawl_at ? new Date(String(row.next_crawl_at)) : null,
    crawl_config: (row.crawl_config as Record<string, unknown>) ?? {},
    created_at: new Date(String(row.created_at)),
    updated_at: new Date(String(row.updated_at)),
  }));
}

export async function setSourceEnabled(id: string, enabled: boolean): Promise<void> {
  await sql`
    UPDATE sources
    SET enabled = ${enabled},
        updated_at = now()
    WHERE id = ${id}::uuid
  `;
}

export async function setSourceInterval(
  id: string,
  crawlIntervalMinutes: number,
): Promise<void> {
  if (!Number.isFinite(crawlIntervalMinutes) || crawlIntervalMinutes < 5) {
    throw new Error("crawl_interval_minutes must be >= 5");
  }
  await sql`
    UPDATE sources
    SET crawl_interval_minutes = ${Math.floor(crawlIntervalMinutes)},
        updated_at = now()
    WHERE id = ${id}::uuid
  `;
}

export async function listCrawlRuns(limit = 50): Promise<CrawlRunRow[]> {
  const rows = await sql`
    SELECT r.*, s.name AS source_name
    FROM crawl_runs r
    LEFT JOIN sources s ON s.id = r.source_id
    ORDER BY r.started_at DESC
    LIMIT ${limit}
  `;
  return rows.map((row) => ({
    id: String(row.id),
    source_id: row.source_id ? String(row.source_id) : null,
    source_name: row.source_name ? String(row.source_name) : null,
    started_at: new Date(String(row.started_at)),
    finished_at: row.finished_at ? new Date(String(row.finished_at)) : null,
    status: row.status as CrawlRunRow["status"],
    pages_fetched: Number(row.pages_fetched),
    candidates_found: Number(row.candidates_found),
    giveaways_created: Number(row.giveaways_created),
    giveaways_updated: Number(row.giveaways_updated),
    errors_count: Number(row.errors_count),
    error_summary: row.error_summary != null ? String(row.error_summary) : null,
    created_at: new Date(String(row.created_at)),
  }));
}

export async function listEntryMethods(): Promise<string[]> {
  const rows = await sql`
    SELECT DISTINCT entry_method
    FROM giveaways
    WHERE entry_method IS NOT NULL AND entry_method <> ''
    ORDER BY entry_method
  `;
  return rows.map((r) => String(r.entry_method));
}
