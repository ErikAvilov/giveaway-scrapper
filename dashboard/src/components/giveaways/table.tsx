"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { GiveawayBadges } from "@/components/giveaways/badges";
import {
  clearGiveawayReminderAction,
  setGiveawayReminderAction,
  updateGiveawayManualStatusAction,
} from "@/server/actions";
import type { GiveawayRow, ManualStatus } from "@/lib/types";
import {
  cn,
  formatDateShort,
  formatEur,
  formatRelativeHours,
  hostnameFromUrl,
} from "@/lib/utils";

const MANUAL_ACTIONS: { status: ManualStatus; label: string }[] = [
  { status: "interested", label: "Interested" },
  { status: "entered", label: "Entered" },
  { status: "ignored", label: "Ignore" },
  { status: "won", label: "Won" },
  { status: "lost", label: "Lost" },
];

const REMINDER_PRESETS: { hours: number; label: string }[] = [
  { hours: 6, label: "6 h" },
  { hours: 12, label: "12 h" },
  { hours: 24, label: "24 h" },
  { hours: 48, label: "48 h" },
  { hours: 72, label: "3 j" },
  { hours: 168, label: "7 j" },
];

const actionBtn =
  "flex h-full min-h-16 w-full cursor-pointer items-center justify-center rounded-xl border-2 px-2 text-center text-sm font-bold leading-tight transition-[background-color,border-color,transform,box-shadow] duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950 disabled:cursor-wait disabled:opacity-40 active:scale-[0.98]";

const actionIdle =
  "border-zinc-400 bg-zinc-800 text-zinc-50 shadow-sm hover:border-sky-400 hover:bg-sky-900 hover:text-white hover:shadow-[0_0_16px_rgba(56,189,248,0.35)] dark:border-zinc-500";

const actionActive =
  "border-sky-300 bg-sky-600 text-white shadow-md hover:bg-sky-500";

const remindIdle =
  "border-amber-700/70 bg-amber-950 text-amber-50 shadow-sm hover:border-amber-300 hover:bg-amber-700 hover:text-white hover:shadow-[0_0_16px_rgba(251,191,36,0.35)]";

const remindActive =
  "border-amber-300 bg-amber-500 text-zinc-950 shadow-md hover:bg-amber-400";

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
  const [customHours, setCustomHours] = useState<Record<string, string>>({});

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

  function setReminder(id: string, hours: number) {
    if (!Number.isFinite(hours) || hours < 1 || hours > 24 * 30) return;
    startTransition(async () => {
      await setGiveawayReminderAction(id, Math.trunc(hours));
      setCustomHours((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      router.refresh();
    });
  }

  function clearReminder(id: string) {
    startTransition(async () => {
      await clearGiveawayReminderAction(id);
      router.refresh();
    });
  }

  function applyCustom(id: string) {
    const raw = (customHours[id] ?? "").trim();
    const hours = Number(raw);
    if (!Number.isFinite(hours) || hours < 1) return;
    setReminder(id, hours);
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
        const unwanted = g.wanted_prize === false;
        const due = g.reminder_due;
        const customValue = customHours[g.id] ?? "";
        const customNum = Number(customValue);
        const customValid =
          customValue.trim() !== "" &&
          Number.isFinite(customNum) &&
          customNum >= 1 &&
          customNum <= 24 * 30;

        return (
          <article
            key={g.id}
            className={cn(
              "space-y-3 p-3",
              due
                ? "bg-amber-50/70 dark:bg-amber-950/20"
                : unwanted
                  ? "bg-zinc-50/80 text-zinc-400 opacity-70 dark:bg-zinc-950/40 dark:text-zinc-500"
                  : "bg-white hover:bg-zinc-50 dark:bg-transparent dark:hover:bg-zinc-900/40",
            )}
          >
            <div className="min-w-0 space-y-2">
              <a
                href={g.entry_url || g.canonical_url}
                target="_blank"
                rel="noreferrer"
                className={cn(
                  "block text-lg font-semibold leading-snug hover:underline",
                  unwanted ? "text-zinc-500" : "text-zinc-900 dark:text-zinc-50",
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
                {g.remind_at ? (
                  <div>
                    <dt className="inline text-zinc-500">Rappel · </dt>
                    <dd
                      className={cn(
                        "inline",
                        due ? "font-semibold text-amber-700 dark:text-amber-300" : "",
                      )}
                    >
                      {formatRelativeHours(g.remind_at)}
                      {g.reminder_hours ? ` (${g.reminder_hours} h)` : ""}
                    </dd>
                  </div>
                ) : null}
              </dl>
            </div>

            <div
              className="grid min-h-16 grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5"
              role="group"
              aria-label="Statut"
            >
              {MANUAL_ACTIONS.map((a) => {
                const active = g.manual_status === a.status;
                return (
                  <button
                    key={a.status}
                    type="button"
                    disabled={pending}
                    onClick={() => setManual(g.id, a.status)}
                    className={cn(actionBtn, active ? actionActive : actionIdle)}
                  >
                    {a.label}
                  </button>
                );
              })}
            </div>

            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-300">
                Rappel / reconsultation
              </div>
              <div
                className="grid min-h-16 grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8"
                role="group"
                aria-label="Rappel"
              >
                {REMINDER_PRESETS.map((preset) => {
                  const active = g.reminder_hours === preset.hours && !due;
                  return (
                    <button
                      key={preset.hours}
                      type="button"
                      disabled={pending}
                      onClick={() => setReminder(g.id, preset.hours)}
                      className={cn(actionBtn, active ? remindActive : remindIdle)}
                    >
                      {preset.label}
                    </button>
                  );
                })}
                <button
                  type="button"
                  disabled={pending || !g.remind_at}
                  onClick={() => clearReminder(g.id)}
                  className={cn(
                    actionBtn,
                    "border-zinc-500 bg-zinc-700 text-zinc-100 hover:border-red-400 hover:bg-red-800 hover:text-white hover:shadow-[0_0_16px_rgba(248,113,113,0.35)] disabled:opacity-30",
                  )}
                >
                  Clear
                </button>
                <form
                  className="col-span-2 flex min-h-16 overflow-hidden rounded-xl border-2 border-amber-700/70 bg-amber-950 shadow-sm transition-[border-color,box-shadow] duration-150 focus-within:border-amber-300 focus-within:shadow-[0_0_16px_rgba(251,191,36,0.35)] sm:col-span-2 lg:col-span-1"
                  onSubmit={(e) => {
                    e.preventDefault();
                    applyCustom(g.id);
                  }}
                >
                  <input
                    type="number"
                    min={1}
                    max={24 * 30}
                    step={1}
                    inputMode="numeric"
                    placeholder="ex. 14"
                    aria-label="Heures de rappel personnalisées"
                    value={customValue}
                    disabled={pending}
                    onChange={(e) =>
                      setCustomHours((prev) => ({ ...prev, [g.id]: e.target.value }))
                    }
                    className="min-w-0 flex-1 bg-transparent px-3 text-center text-base font-bold text-amber-50 placeholder:text-amber-200/50 outline-none"
                  />
                  <button
                    type="submit"
                    disabled={pending || !customValid}
                    className={cn(
                      "min-w-16 cursor-pointer border-l-2 border-amber-700/70 px-3 text-sm font-bold text-amber-50 transition-colors",
                      "hover:bg-amber-600 hover:text-white",
                      "disabled:cursor-not-allowed disabled:opacity-40",
                    )}
                  >
                    OK
                  </button>
                </form>
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}
