"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  toggleSourceEnabledAction,
  updateSourceIntervalAction,
} from "@/server/actions";
import type { SourceRow } from "@/lib/types";
import { formatDate } from "@/lib/utils";

export function SourcesTable({ sources }: { sources: SourceRow[] }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  if (!sources.length) {
    return (
      <div className="px-3 py-10 text-center text-xs text-zinc-500">
        No sources yet. Seed them from the collector CLI.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[900px] border-collapse text-left text-xs">
        <thead className="bg-zinc-100 text-[10px] uppercase tracking-wide text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
          <tr className="border-b border-zinc-200 dark:border-zinc-800">
            {["Name", "URL", "Type", "Enabled", "Interval (min)", "Last crawl", "Next crawl", ""].map(
              (h) => (
                <th key={h || "a"} className="px-2 py-2 font-semibold">
                  {h}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {sources.map((s) => (
            <tr
              key={s.id}
              className="border-b border-zinc-100 hover:bg-zinc-50 dark:border-zinc-900 dark:hover:bg-zinc-900/50"
            >
              <td className="px-2 py-2 font-medium">{s.name}</td>
              <td className="max-w-[280px] truncate px-2 py-2 font-mono text-[11px]">
                <a
                  href={s.base_url}
                  target="_blank"
                  rel="noreferrer"
                  className="hover:underline"
                >
                  {s.base_url}
                </a>
              </td>
              <td className="px-2 py-2">{s.source_type}</td>
              <td className="px-2 py-2">{s.enabled ? "yes" : "no"}</td>
              <td className="px-2 py-2">
                <form
                  className="flex items-center gap-1"
                  onSubmit={(e) => {
                    e.preventDefault();
                    const fd = new FormData(e.currentTarget);
                    const minutes = Number(fd.get("interval"));
                    startTransition(async () => {
                      await updateSourceIntervalAction(s.id, minutes);
                      router.refresh();
                    });
                  }}
                >
                  <Input
                    name="interval"
                    type="number"
                    min={5}
                    defaultValue={s.crawl_interval_minutes}
                    className="w-20"
                    disabled={pending}
                  />
                  <Button type="submit" size="xs" variant="outline" disabled={pending}>
                    Save
                  </Button>
                </form>
              </td>
              <td className="px-2 py-2 whitespace-nowrap">{formatDate(s.last_crawled_at)}</td>
              <td className="px-2 py-2 whitespace-nowrap">{formatDate(s.next_crawl_at)}</td>
              <td className="px-2 py-2">
                <Button
                  size="xs"
                  variant={s.enabled ? "outline" : "secondary"}
                  disabled={pending}
                  onClick={() =>
                    startTransition(async () => {
                      await toggleSourceEnabledAction(s.id, !s.enabled);
                      router.refresh();
                    })
                  }
                >
                  {s.enabled ? "Disable" : "Enable"}
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
