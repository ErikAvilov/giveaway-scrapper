"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { GiveawayBadges } from "@/components/giveaways/badges";
import { updateGiveawayManualStatusAction } from "@/server/actions";
import type { GiveawayRow, ManualStatus } from "@/lib/types";
import { cn, formatDateShort, formatEur, hostnameFromUrl } from "@/lib/utils";

const MANUAL_ACTIONS: { status: ManualStatus; label: string }[] = [
  { status: "interested", label: "Interested" },
  { status: "entered", label: "Entered" },
  { status: "ignored", label: "Ignore" },
  { status: "won", label: "Won" },
  { status: "lost", label: "Lost" },
];

export function GiveawaysTable({
  rows,
  selectedId,
  viewingIgnored = false,
}: {
  rows: GiveawayRow[];
  selectedId?: string;
  viewingIgnored?: boolean;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  function setManual(id: string, status: ManualStatus) {
    startTransition(async () => {
      await updateGiveawayManualStatusAction(id, status);
      if (status === "ignored" && !viewingIgnored) {
        const params = new URLSearchParams(window.location.search);
        params.delete("id");
        const qs = params.toString();
        router.replace(qs ? `/giveaways?${qs}` : "/giveaways");
      } else if (status !== "ignored" && viewingIgnored && selectedId === id) {
        router.replace("/giveaways?manual_status=ignored&wanted=0");
      } else {
        router.refresh();
      }
    });
  }

  if (!rows.length) {
    return (
      <div className="px-4 py-12 text-center text-sm text-zinc-500">
        No giveaways match these filters.
      </div>
    );
  }

  return (
    <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
      {rows.map((g) => {
        const selected = selectedId === g.id;
        const unwanted = g.wanted_prize === false;
        return (
          <article
            key={g.id}
            className={cn(
              "grid grid-cols-1 gap-3 p-3 lg:grid-cols-[minmax(0,1fr)_minmax(520px,42%)] lg:items-stretch",
              selected
                ? "bg-sky-50 dark:bg-sky-950/40"
                : unwanted
                  ? "bg-zinc-50/80 text-zinc-400 opacity-70 dark:bg-zinc-950/40 dark:text-zinc-500"
                  : "bg-white hover:bg-zinc-50 dark:bg-transparent dark:hover:bg-zinc-900/50",
            )}
          >
            <div className="min-w-0 space-y-2">
              <a
                href={g.entry_url || g.canonical_url}
                target="_blank"
                rel="noreferrer"
                className={cn(
                  "block text-lg font-semibold leading-snug hover:underline",
                  unwanted
                    ? "text-zinc-500"
                    : "text-zinc-900 dark:text-zinc-50",
                )}
              >
                {g.prize || g.title || "Untitled"}
              </a>
              <GiveawayBadges giveaway={g} />
              <dl className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-zinc-600 dark:text-zinc-400">
                <div>
                  <dt className="inline text-zinc-500">Site · </dt>
                  <dd className="inline font-mono">{hostnameFromUrl(g.canonical_url)}</dd>
                </div>
                <div>
                  <dt className="inline text-zinc-500">Value · </dt>
                  <dd className="inline tabular-nums">{formatEur(g.prize_value_eur)}</dd>
                </div>
                <div>
                  <dt className="inline text-zinc-500">Priority · </dt>
                  <dd className="inline tabular-nums">
                    {g.prize_priority == null ? "—" : g.prize_priority}
                  </dd>
                </div>
                <div>
                  <dt className="inline text-zinc-500">Category · </dt>
                  <dd className="inline font-mono text-xs">{g.prize_category || "—"}</dd>
                </div>
                <div>
                  <dt className="inline text-zinc-500">France · </dt>
                  <dd className="inline">
                    {g.eligible_france == null ? "—" : g.eligible_france ? "Yes" : "No"}
                  </dd>
                </div>
                <div>
                  <dt className="inline text-zinc-500">Free · </dt>
                  <dd className="inline">
                    {g.free_entry == null ? "—" : g.free_entry ? "Yes" : "No"}
                  </dd>
                </div>
                <div>
                  <dt className="inline text-zinc-500">Method · </dt>
                  <dd className="inline">{g.entry_method || "—"}</dd>
                </div>
                <div>
                  <dt className="inline text-zinc-500">Discovered · </dt>
                  <dd className="inline">{formatDateShort(g.discovered_at)}</dd>
                </div>
                <div>
                  <dt className="inline text-zinc-500">Ends · </dt>
                  <dd className="inline">{formatDateShort(g.end_at)}</dd>
                </div>
                <div>
                  <dt className="inline text-zinc-500">Conf. · </dt>
                  <dd className="inline tabular-nums">
                    {g.confidence == null ? "—" : g.confidence.toFixed(2)}
                  </dd>
                </div>
                <div>
                  <dt className="inline text-zinc-500">Status · </dt>
                  <dd className="inline">{g.status}</dd>
                </div>
              </dl>
            </div>

            <div
              className="grid h-full min-h-28 grid-cols-5 gap-2"
              role="group"
              aria-label="Actions"
            >
              {MANUAL_ACTIONS.map((a) => {
                const active = g.manual_status === a.status;
                return (
                  <button
                    key={a.status}
                    type="button"
                    disabled={pending}
                    onClick={() => setManual(g.id, a.status)}
                    className={cn(
                      "flex h-full min-h-28 w-full cursor-pointer items-center justify-center rounded-xl border-2 px-2 text-center text-base font-bold leading-tight",
                      "transition-[background-color,border-color,transform,box-shadow] duration-150",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950",
                      "disabled:cursor-wait disabled:opacity-40",
                      active
                        ? "border-sky-300 bg-sky-600 text-white shadow-md hover:bg-sky-500 active:scale-[0.98]"
                        : "border-zinc-400 bg-zinc-800 text-zinc-50 shadow-sm hover:border-sky-400 hover:bg-sky-900 hover:text-white hover:shadow-[0_0_16px_rgba(56,189,248,0.35)] active:scale-[0.98] dark:border-zinc-500",
                    )}
                  >
                    {a.label}
                  </button>
                );
              })}
            </div>
          </article>
        );
      })}
    </div>
  );
}
