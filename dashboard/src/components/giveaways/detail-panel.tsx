"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { ExternalLink, X } from "lucide-react";
import { GiveawayBadges } from "@/components/giveaways/badges";
import { Button } from "@/components/ui/button";
import { updateGiveawayManualStatusAction } from "@/server/actions";
import type { GiveawayRow, ManualStatus } from "@/lib/types";
import { formatDate, formatEur } from "@/lib/utils";

export function GiveawayDetailPanel({
  giveaway,
  viewingIgnored = false,
}: {
  giveaway: GiveawayRow;
  viewingIgnored?: boolean;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  function setManual(status: ManualStatus) {
    startTransition(async () => {
      await updateGiveawayManualStatusAction(giveaway.id, status);
      if (status === "ignored" && !viewingIgnored) {
        const params = new URLSearchParams(window.location.search);
        params.delete("id");
        const qs = params.toString();
        router.replace(qs ? `/giveaways?${qs}` : "/giveaways");
      } else if (status !== "ignored" && viewingIgnored) {
        router.replace("/giveaways?manual_status=ignored&wanted=0");
      } else {
        router.refresh();
      }
    });
  }

  function close() {
    if (viewingIgnored) {
      router.push("/giveaways?manual_status=ignored&wanted=0");
    } else {
      const params = new URLSearchParams(window.location.search);
      params.delete("id");
      const qs = params.toString();
      router.push(qs ? `/giveaways?${qs}` : "/giveaways");
    }
  }

  return (
    <aside className="flex h-full w-full max-w-lg flex-col border-l border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex items-start justify-between gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <div>
          <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
            {giveaway.title || giveaway.prize || "Giveaway"}
          </h2>
          <p className="text-sm text-zinc-500">{giveaway.domain}</p>
        </div>
        <Button variant="ghost" size="xs" onClick={close} aria-label="Close">
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4 text-sm">
        <GiveawayBadges giveaway={giveaway} />

        <dl className="grid grid-cols-[110px_1fr] gap-x-2 gap-y-1.5">
          <dt className="text-zinc-500">Prize</dt>
          <dd>{giveaway.prize || "—"}</dd>
          <dt className="text-zinc-500">Value</dt>
          <dd>{formatEur(giveaway.prize_value_eur)}</dd>
          <dt className="text-zinc-500">Wanted</dt>
          <dd>
            {giveaway.wanted_prize == null
              ? "unknown"
              : giveaway.wanted_prize
                ? "yes"
                : "no"}
          </dd>
          <dt className="text-zinc-500">Category</dt>
          <dd>{giveaway.prize_category || "—"}</dd>
          <dt className="text-zinc-500">Priority</dt>
          <dd>{giveaway.prize_priority == null ? "—" : giveaway.prize_priority}</dd>
          <dt className="text-zinc-500">Requires travel</dt>
          <dd>
            {giveaway.requires_travel == null
              ? "—"
              : giveaway.requires_travel
                ? "yes"
                : "no"}
          </dd>
          <dt className="text-zinc-500">Extra spend</dt>
          <dd>
            {giveaway.requires_additional_spend == null
              ? "—"
              : giveaway.requires_additional_spend
                ? "yes"
                : "no"}
          </dd>
          <dt className="text-zinc-500">Preference</dt>
          <dd className="break-words">{giveaway.preference_reason || "—"}</dd>
          <dt className="text-zinc-500">Method</dt>
          <dd>{giveaway.entry_method || "—"}</dd>
          <dt className="text-zinc-500">Source</dt>
          <dd>{giveaway.source_name || "—"}</dd>
          <dt className="text-zinc-500">Confidence</dt>
          <dd>{giveaway.confidence == null ? "—" : giveaway.confidence.toFixed(2)}</dd>
          <dt className="text-zinc-500">Status</dt>
          <dd>
            {giveaway.status} / {giveaway.manual_status}
          </dd>
          <dt className="text-zinc-500">Start</dt>
          <dd>{formatDate(giveaway.start_at)}</dd>
          <dt className="text-zinc-500">End</dt>
          <dd>{formatDate(giveaway.end_at)}</dd>
          <dt className="text-zinc-500">Discovered</dt>
          <dd>{formatDate(giveaway.discovered_at)}</dd>
          <dt className="text-zinc-500">Analyzed</dt>
          <dd>{formatDate(giveaway.analyzed_at)}</dd>
          <dt className="text-zinc-500">France</dt>
          <dd>
            {giveaway.eligible_france == null
              ? "unknown"
              : giveaway.eligible_france
                ? "eligible"
                : "not eligible"}
          </dd>
        </dl>

        <div className="flex flex-wrap gap-2">
          <a href={giveaway.canonical_url} target="_blank" rel="noreferrer">
            <Button size="md" variant="secondary">
              Open giveaway <ExternalLink className="h-4 w-4" />
            </Button>
          </a>
          {giveaway.entry_url ? (
            <a href={giveaway.entry_url} target="_blank" rel="noreferrer">
              <Button size="md" variant="secondary">
                Open entry <ExternalLink className="h-4 w-4" />
              </Button>
            </a>
          ) : null}
          {giveaway.terms_url ? (
            <a href={giveaway.terms_url} target="_blank" rel="noreferrer">
              <Button size="md" variant="outline">
                Terms <ExternalLink className="h-4 w-4" />
              </Button>
            </a>
          ) : null}
        </div>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {(
            [
              ["interested", "Interested"],
              ["entered", "Mark entered"],
              ["ignored", "Ignore"],
              ["won", "Won"],
              ["lost", "Lost"],
              ["none", "Reset"],
            ] as const
          ).map(([status, label]) => (
            <Button
              key={status}
              size="fill"
              className="min-h-12"
              variant={giveaway.manual_status === status ? "default" : "outline"}
              disabled={pending}
              onClick={() => setManual(status)}
            >
              {label}
            </Button>
          ))}
        </div>

        <Section title="Description">
          <p className="whitespace-pre-wrap text-zinc-700 dark:text-zinc-300">
            {giveaway.description || "—"}
          </p>
        </Section>

        <Section title="Requirements">
          <Requirements analysis={giveaway.analysis_json} />
        </Section>

        <Section title="Raw excerpt">
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded border border-zinc-200 bg-zinc-50 p-2 font-mono text-[11px] text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
            {giveaway.raw_excerpt || "—"}
          </pre>
        </Section>

        <Section title="Gemini analysis JSON">
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded border border-zinc-200 bg-zinc-50 p-2 font-mono text-[11px] text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
            {giveaway.analysis_json
              ? JSON.stringify(giveaway.analysis_json, null, 2)
              : "—"}
          </pre>
        </Section>
      </div>
    </aside>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500">
        {title}
      </h3>
      {children}
    </section>
  );
}

function Requirements({ analysis }: { analysis: Record<string, unknown> | null }) {
  const reqs = analysis?.requirements;
  if (!Array.isArray(reqs) || !reqs.length) {
    return <p className="text-zinc-500">—</p>;
  }
  return (
    <ul className="list-disc space-y-0.5 pl-4 text-zinc-700 dark:text-zinc-300">
      {reqs.map((r, i) => (
        <li key={`${i}-${String(r)}`}>{String(r)}</li>
      ))}
    </ul>
  );
}
