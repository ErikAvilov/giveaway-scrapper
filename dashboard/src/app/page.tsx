import Link from "next/link";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { GiveawayBadges } from "@/components/giveaways/badges";
import { Badge } from "@/components/ui/badge";
import type { CrawlRunRow, GiveawayRow, OverviewStats } from "@/lib/types";
import {
  getOverviewStats,
  listCrawlRuns,
  listEndingSoon,
  listRecentGiveaways,
} from "@/server/queries";
import { formatDate, formatDateShort, formatDuration, formatEur } from "@/lib/utils";

export const dynamic = "force-dynamic";

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border border-zinc-200 bg-white px-3 py-2 dark:border-zinc-800 dark:bg-zinc-950">
      <div className="text-xs uppercase tracking-wide text-zinc-500">{label}</div>
      <div className="mt-0.5 text-2xl font-semibold tabular-nums text-zinc-900 dark:text-zinc-50">
        {value}
      </div>
    </div>
  );
}

export default async function OverviewPage() {
  let error: string | null = null;
  let stats: OverviewStats | null = null;
  let recent: GiveawayRow[] = [];
  let ending: GiveawayRow[] = [];
  let runs: CrawlRunRow[] = [];

  try {
    [stats, recent, ending, runs] = await Promise.all([
      getOverviewStats(),
      listRecentGiveaways(8),
      listEndingSoon(8),
      listCrawlRuns(8),
    ]);
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load overview";
  }

  return (
    <div className="space-y-4 p-4">
      <header>
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-50">Overview</h1>
        <p className="text-sm text-zinc-500">Live counters from Neon</p>
      </header>

      {error ? (
        <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          {error}
        </div>
      ) : null}

      {stats ? (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-5">
          <Link href="/giveaways">
            <Stat label="Inbox" value={stats.inbox} />
          </Link>
          <Link href="/giveaways?view=interested">
            <Stat label="Interested" value={stats.interested} />
          </Link>
          <Stat label="Ending 24h" value={stats.ending_24h} />
          <Stat label="Ending 7d" value={stats.ending_7d} />
          <Stat label="Discovered today" value={stats.discovered_today} />
          <Link href="/giveaways?reminders_due=1&wanted=0&france=0&sort=remind_at">
            <Stat label="Rappels dus" value={stats.reminders_due} />
          </Link>
          <Link href="/giveaways?view=entered&wanted=0&france=0&status=all">
            <Stat label="Entered" value={stats.entered} />
          </Link>
          <Link href="/giveaways?view=ignored&wanted=0&france=0&status=all">
            <Stat label="Ignored" value={stats.ignored} />
          </Link>
          <Stat label="Won" value={stats.won} />
        </div>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel className="xl:col-span-1">
          <PanelHeader title="Recent discoveries" />
          <ul className="divide-y divide-zinc-100 dark:divide-zinc-900">
            {recent.length === 0 ? (
              <li className="px-3 py-6 text-center text-sm text-zinc-500">No discoveries yet</li>
            ) : (
              recent.map((g) => (
                <li key={g.id} className="px-3 py-2">
                  <Link
                    href={`/giveaways?id=${g.id}`}
                    className="text-sm font-medium hover:underline"
                  >
                    {g.prize || g.title || g.domain}
                  </Link>
                  <div className="mt-0.5 flex items-center justify-between gap-2">
                    <span className="text-[11px] text-zinc-500">
                      {formatDateShort(g.discovered_at)} · {formatEur(g.prize_value_eur)}
                    </span>
                  </div>
                  <div className="mt-1">
                    <GiveawayBadges giveaway={g} />
                  </div>
                </li>
              ))
            )}
          </ul>
        </Panel>

        <Panel className="xl:col-span-1">
          <PanelHeader title="Ending soon" />
          <ul className="divide-y divide-zinc-100 dark:divide-zinc-900">
            {ending.length === 0 ? (
              <li className="px-3 py-6 text-center text-sm text-zinc-500">Nothing ending soon</li>
            ) : (
              ending.map((g) => (
                <li key={g.id} className="px-3 py-2">
                  <Link
                    href={`/giveaways?id=${g.id}`}
                    className="text-sm font-medium hover:underline"
                  >
                    {g.prize || g.title || g.domain}
                  </Link>
                  <div className="mt-0.5 text-[11px] text-zinc-500">
                    Ends {formatDate(g.end_at)}
                  </div>
                </li>
              ))
            )}
          </ul>
        </Panel>

        <Panel className="xl:col-span-1">
          <PanelHeader title="Recent crawler activity" />
          <ul className="divide-y divide-zinc-100 dark:divide-zinc-900">
            {runs.length === 0 ? (
              <li className="px-3 py-6 text-center text-sm text-zinc-500">No crawl runs yet</li>
            ) : (
              runs.map((r) => (
                <li key={r.id} className="px-3 py-3 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{r.source_name || "Unknown source"}</span>
                    <Badge
                      variant={
                        r.status === "failed"
                          ? "danger"
                          : r.status === "success"
                            ? "free"
                            : "warn"
                      }
                    >
                      {r.status}
                    </Badge>
                  </div>
                  <div className="mt-0.5 text-[11px] text-zinc-500">
                    {formatDate(r.started_at)} · {formatDuration(r.started_at, r.finished_at)} ·{" "}
                    {r.pages_fetched} pages · {r.candidates_found} candidates
                  </div>
                </li>
              ))
            )}
          </ul>
        </Panel>
      </div>
    </div>
  );
}
