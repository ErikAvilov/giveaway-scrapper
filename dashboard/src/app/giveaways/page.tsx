import { GiveawayDetailPanel } from "@/components/giveaways/detail-panel";
import { GiveawayFiltersBar } from "@/components/giveaways/filters";
import { GiveawaysTable } from "@/components/giveaways/table";
import { Panel } from "@/components/ui/panel";
import type { GiveawaySort, ManualStatus, PrizeCategory } from "@/lib/types";
import {
  countIgnoredGiveaways,
  getGiveaway,
  listEntryMethods,
  listGiveaways,
  listSources,
} from "@/server/queries";
import Link from "next/link";

export const dynamic = "force-dynamic";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function one(v: string | string[] | undefined): string | undefined {
  if (Array.isArray(v)) return v[0];
  return v;
}

/** Prefer last value when checkbox+hidden both submit (wanted=0&wanted=1). */
function oneLast(v: string | string[] | undefined): string | undefined {
  if (Array.isArray(v)) return v[v.length - 1];
  return v;
}

export default async function GiveawaysPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const sp = await searchParams;
  const wantedParam = oneLast(sp.wanted);
  const franceParam = oneLast(sp.france);
  const hideGoneParam = oneLast(sp.hide_gone);
  const acceptableParam = oneLast(sp.acceptable);
  const values = {
    q: one(sp.q),
    status: one(sp.status),
    manual_status: one(sp.manual_status),
    source_id: one(sp.source_id),
    entry_method: one(sp.entry_method),
    prize_category: one(sp.prize_category),
    sort: one(sp.sort),
    min_value: one(sp.min_value),
    france: franceParam,
    free: one(sp.free),
    ending_soon: one(sp.ending_soon),
    wanted: wantedParam,
    hide_gone: hideGoneParam,
    acceptable: acceptableParam,
    public_social: one(sp.public_social),
    entry_rejection_reason: one(sp.entry_rejection_reason),
    reminders_due: one(sp.reminders_due),
    has_reminder: one(sp.has_reminder),
    show_unknown_france: one(sp.show_unknown_france),
    show_ineligible: one(sp.show_ineligible),
    show_unwanted: one(sp.show_unwanted),
    id: one(sp.id),
  };

  // Defaults: Wanted + France eligible + hide dead links + acceptable entry + active.
  const wantedOnly = values.wanted !== "0";
  const franceOnly = values.france !== "0";
  const hideGone = values.hide_gone !== "0";
  const publicSocialInspect = values.public_social === "1";
  const acceptableOnly = publicSocialInspect
    ? false
    : values.acceptable !== "0";
  const viewingIgnored = values.manual_status === "ignored";
  const viewingRemindersDue = values.reminders_due === "1";
  const statusDefault = (values.status as "active" | "expired" | "all") || "active";
  const sortDefault =
    (values.sort as GiveawaySort) ||
    (viewingRemindersDue ? "remind_at" : "priority");

  let error: string | null = null;
  let rows: Awaited<ReturnType<typeof listGiveaways>>["rows"] = [];
  let total = 0;
  let ignoredCount = 0;
  let sources: Awaited<ReturnType<typeof listSources>> = [];
  let methods: string[] = [];
  let selected = null as Awaited<ReturnType<typeof getGiveaway>>;

  try {
    const [list, src, meth, ignored] = await Promise.all([
      listGiveaways({
        q: values.q,
        status: statusDefault,
        manual_status: (values.manual_status as ManualStatus | "all") || "all",
        source_id: values.source_id || undefined,
        entry_method: values.entry_method || undefined,
        prize_category: (values.prize_category as PrizeCategory | "all") || "all",
        sort: sortDefault,
        min_value: values.min_value ? Number(values.min_value) : undefined,
        france: viewingIgnored ? false : franceOnly,
        free: values.free === "1" ? true : undefined,
        ending_soon: values.ending_soon === "1" ? true : undefined,
        reminders_due: values.reminders_due === "1" ? true : undefined,
        has_reminder: values.has_reminder === "1" ? true : undefined,
        wanted_only: viewingIgnored ? false : wantedOnly,
        hide_gone: viewingIgnored ? false : hideGone,
        acceptable_only: viewingIgnored ? false : acceptableOnly,
        public_social_required: publicSocialInspect,
        entry_rejection_reason: values.entry_rejection_reason || undefined,
        show_unknown_france: values.show_unknown_france === "1",
        show_ineligible: values.show_ineligible === "1",
        show_unwanted: values.show_unwanted === "1",
        limit: 100,
      }),
      listSources(),
      listEntryMethods(),
      countIgnoredGiveaways(),
    ]);
    rows = list.rows;
    total = list.total;
    sources = src;
    methods = meth;
    ignoredCount = ignored;
    if (values.id) selected = await getGiveaway(values.id);
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load giveaways";
  }

  return (
    <div className="flex h-[calc(100vh)] min-h-0">
      <div className="min-w-0 flex-1 overflow-auto p-5">
        <header className="mb-4 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h1 className="text-xl font-semibold">
              {viewingIgnored
                ? "Ignored list"
                : viewingRemindersDue
                  ? "Rappels dus"
                  : publicSocialInspect
                    ? "Public social action"
                    : "Giveaways"}
            </h1>
            <p className="text-sm text-zinc-500">
              {total} matching rows
              {!viewingIgnored ? " · ignored hidden from this view" : null}
            </p>
          </div>
          <div className="flex items-center gap-3 text-sm">
            {viewingRemindersDue ? (
              <Link href="/giveaways" className="text-sky-700 hover:underline dark:text-sky-400">
                ← Back to main view
              </Link>
            ) : (
              <Link
                href="/giveaways?reminders_due=1&wanted=0&france=0&sort=remind_at"
                className="text-amber-700 hover:underline dark:text-amber-400"
              >
                Rappels dus
              </Link>
            )}
            {viewingIgnored ? (
              <Link href="/giveaways" className="text-sky-700 hover:underline dark:text-sky-400">
                ← Back to main view
              </Link>
            ) : (
              <Link
                href="/giveaways?manual_status=ignored&wanted=0"
                className="text-zinc-600 hover:underline dark:text-zinc-400"
              >
                Ignored list ({ignoredCount})
              </Link>
            )}
          </div>
        </header>

        {error ? (
          <div className="mb-3 rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-800">
            {error}
          </div>
        ) : null}

        <Panel>
          <GiveawayFiltersBar
            sources={sources}
            entryMethods={methods}
            values={{
              ...values,
              status: statusDefault,
              sort: sortDefault,
              wanted: viewingIgnored ? "0" : wantedOnly ? "1" : "0",
              france: viewingIgnored ? "0" : franceOnly ? "1" : "0",
              hide_gone: viewingIgnored ? "0" : hideGone ? "1" : "0",
              acceptable: viewingIgnored || publicSocialInspect
                ? "0"
                : acceptableOnly
                  ? "1"
                  : "0",
              public_social: publicSocialInspect ? "1" : undefined,
              manual_status: values.manual_status ?? "all",
              reminders_due: values.reminders_due,
              has_reminder: values.has_reminder,
            }}
          />
          <GiveawaysTable
            rows={rows}
            selectedId={values.id}
            viewingIgnored={viewingIgnored}
          />
        </Panel>
      </div>
      {selected ? (
        <GiveawayDetailPanel
          giveaway={selected}
          viewingIgnored={viewingIgnored}
        />
      ) : null}
    </div>
  );
}
