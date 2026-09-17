import { GiveawayDetailPanel } from "@/components/giveaways/detail-panel";
import { GiveawayFiltersBar } from "@/components/giveaways/filters";
import { GiveawaysTable } from "@/components/giveaways/table";
import { Panel } from "@/components/ui/panel";
import type { GiveawaySort, InboxView, PrizeCategory } from "@/lib/types";
import {
  getOverviewStats,
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

const VIEWS: { id: InboxView; label: string }[] = [
  { id: "inbox", label: "Inbox" },
  { id: "interested", label: "Interested" },
  { id: "entered", label: "Entered" },
  { id: "ignored", label: "Ignored" },
  { id: "history", label: "History" },
];

function resolveView(raw: string | undefined): InboxView {
  if (raw === "interested") return "interested";
  if (raw === "entered") return "entered";
  if (raw === "ignored") return "ignored";
  if (raw === "history") return "history";
  // Legacy links
  if (raw === "manual_ignored") return "ignored";
  return "inbox";
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
  // Legacy: ?manual_status=ignored → ignored view
  const legacyManual = one(sp.manual_status);
  const view = resolveView(
    one(sp.view) ?? (legacyManual === "ignored" ? "ignored" : undefined),
  );

  const values = {
    q: one(sp.q),
    status: one(sp.status),
    view,
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

  const isHistoryLike =
    view === "entered" || view === "ignored" || view === "history";
  const viewingRemindersDue = values.reminders_due === "1";
  const publicSocialInspect = values.public_social === "1";

  // Defaults for actionable Inbox; history views relax filters.
  const wantedOnly = isHistoryLike ? values.wanted === "1" : values.wanted !== "0";
  const franceOnly = isHistoryLike ? values.france === "1" : values.france !== "0";
  const hideGone = isHistoryLike ? values.hide_gone === "1" : values.hide_gone !== "0";
  const acceptableOnly = publicSocialInspect
    ? false
    : isHistoryLike
      ? values.acceptable === "1"
      : values.acceptable !== "0";

  const statusDefault =
    (values.status as "active" | "expired" | "all") ||
    (isHistoryLike ? "all" : "active");
  const sortDefault =
    (values.sort as GiveawaySort) ||
    (viewingRemindersDue ? "remind_at" : "priority");

  let error: string | null = null;
  let rows: Awaited<ReturnType<typeof listGiveaways>>["rows"] = [];
  let total = 0;
  let sources: Awaited<ReturnType<typeof listSources>> = [];
  let methods: string[] = [];
  let selected = null as Awaited<ReturnType<typeof getGiveaway>>;
  let counts = {
    inbox: 0,
    interested: 0,
    entered: 0,
    ignored: 0,
  };

  try {
    const [list, src, meth, stats] = await Promise.all([
      listGiveaways({
        q: values.q,
        status: statusDefault,
        view,
        source_id: values.source_id || undefined,
        entry_method: values.entry_method || undefined,
        prize_category: (values.prize_category as PrizeCategory | "all") || "all",
        sort: sortDefault,
        min_value: values.min_value ? Number(values.min_value) : undefined,
        france: isHistoryLike ? franceOnly : franceOnly,
        free: values.free === "1" ? true : undefined,
        ending_soon: values.ending_soon === "1" ? true : undefined,
        reminders_due: values.reminders_due === "1" ? true : undefined,
        has_reminder: values.has_reminder === "1" ? true : undefined,
        wanted_only: wantedOnly,
        hide_gone: hideGone,
        acceptable_only: acceptableOnly,
        public_social_required: publicSocialInspect,
        entry_rejection_reason: values.entry_rejection_reason || undefined,
        show_unknown_france: values.show_unknown_france === "1",
        show_ineligible: values.show_ineligible === "1",
        show_unwanted: values.show_unwanted === "1",
        limit: 100,
      }),
      listSources(),
      listEntryMethods(),
      getOverviewStats(),
    ]);
    rows = list.rows;
    total = list.total;
    sources = src;
    methods = meth;
    counts = {
      inbox: stats.inbox,
      interested: stats.interested,
      entered: stats.entered,
      ignored: stats.ignored,
    };
    if (values.id) selected = await getGiveaway(values.id);
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load giveaways";
  }

  const title =
    view === "interested"
      ? "Interested"
      : view === "entered"
        ? "Entered"
        : view === "ignored"
          ? "Ignored"
          : view === "history"
            ? "History"
            : viewingRemindersDue
              ? "Rappels dus"
              : "Inbox";

  function viewHref(id: InboxView): string {
    const params = new URLSearchParams();
    if (id !== "inbox") params.set("view", id);
    if (id === "entered" || id === "ignored" || id === "history") {
      params.set("wanted", "0");
      params.set("france", "0");
      params.set("acceptable", "0");
      params.set("status", "all");
    }
    const qs = params.toString();
    return qs ? `/giveaways?${qs}` : "/giveaways";
  }

  return (
    <div className="flex h-[calc(100vh)] min-h-0">
      <div className="min-w-0 flex-1 overflow-auto p-5">
        <header className="mb-4 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h1 className="text-xl font-semibold">{title}</h1>
            <p className="text-sm text-zinc-500">{total} matching rows</p>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <Link
              href="/giveaways?reminders_due=1&wanted=0&france=0&sort=remind_at&view=inbox"
              className="text-amber-700 hover:underline dark:text-amber-400"
            >
              Rappels dus
            </Link>
          </div>
        </header>

        <nav className="mb-4 flex flex-wrap gap-1 border-b border-zinc-200 pb-2 dark:border-zinc-800">
          {VIEWS.map((v) => {
            const active = view === v.id;
            const count =
              v.id === "inbox"
                ? counts.inbox
                : v.id === "interested"
                  ? counts.interested
                  : v.id === "entered"
                    ? counts.entered
                    : v.id === "ignored"
                      ? counts.ignored
                      : null;
            return (
              <Link
                key={v.id}
                href={viewHref(v.id)}
                className={
                  active
                    ? "rounded px-3 py-1.5 text-sm font-semibold bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                    : "rounded px-3 py-1.5 text-sm text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-900"
                }
              >
                {v.label}
                {count != null ? ` (${count})` : ""}
              </Link>
            );
          })}
        </nav>

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
              wanted: wantedOnly ? "1" : "0",
              france: franceOnly ? "1" : "0",
              hide_gone: hideGone ? "1" : "0",
              acceptable: acceptableOnly ? "1" : "0",
              public_social: publicSocialInspect ? "1" : undefined,
              reminders_due: values.reminders_due,
              has_reminder: values.has_reminder,
              view,
            }}
          />
          <GiveawaysTable
            rows={rows}
            selectedId={values.id}
            viewingIgnored={view === "ignored"}
          />
        </Panel>
      </div>
      {selected ? (
        <GiveawayDetailPanel
          giveaway={selected}
          viewingIgnored={view === "ignored"}
        />
      ) : null}
    </div>
  );
}
