"use client";

import { Fragment, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { CrawlRunRow } from "@/lib/types";
import { formatDate, formatDuration } from "@/lib/utils";

export function CrawlRunsTable({ runs }: { runs: CrawlRunRow[] }) {
  const [openId, setOpenId] = useState<string | null>(null);

  if (!runs.length) {
    return (
      <div className="px-3 py-10 text-center text-xs text-zinc-500">
        No crawl runs recorded yet.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1000px] border-collapse text-left text-xs">
        <thead className="bg-zinc-100 text-[10px] uppercase tracking-wide text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
          <tr className="border-b border-zinc-200 dark:border-zinc-800">
            {[
              "Started",
              "Duration",
              "Source",
              "Pages",
              "Candidates",
              "Created",
              "Updated",
              "Errors",
              "Status",
              "",
            ].map((h) => (
              <th key={h || "a"} className="px-2 py-2 font-semibold">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => {
            const failed = r.status === "failed" || r.errors_count > 0;
            const open = openId === r.id;
            return (
              <Fragment key={r.id}>
                <tr
                  className={`border-b border-zinc-100 dark:border-zinc-900 ${
                    failed ? "bg-red-50/50 dark:bg-red-950/20" : ""
                  }`}
                >
                  <td className="px-2 py-2 whitespace-nowrap">{formatDate(r.started_at)}</td>
                  <td className="px-2 py-2">
                    {formatDuration(r.started_at, r.finished_at)}
                  </td>
                  <td className="px-2 py-2">{r.source_name || "—"}</td>
                  <td className="px-2 py-2 tabular-nums">{r.pages_fetched}</td>
                  <td className="px-2 py-2 tabular-nums">{r.candidates_found}</td>
                  <td className="px-2 py-2 tabular-nums">{r.giveaways_created}</td>
                  <td className="px-2 py-2 tabular-nums">{r.giveaways_updated}</td>
                  <td className="px-2 py-2 tabular-nums">{r.errors_count}</td>
                  <td className="px-2 py-2">
                    <Badge
                      variant={
                        r.status === "failed"
                          ? "danger"
                          : r.status === "partial"
                            ? "warn"
                            : r.status === "success"
                              ? "free"
                              : "default"
                      }
                    >
                      {r.status}
                    </Badge>
                  </td>
                  <td className="px-2 py-2">
                    {r.error_summary ? (
                      <Button
                        size="xs"
                        variant="outline"
                        onClick={() => setOpenId(open ? null : r.id)}
                      >
                        {open ? "Hide error" : "Error"}
                      </Button>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
                {open && r.error_summary ? (
                  <tr className="border-b border-zinc-100 dark:border-zinc-900">
                    <td colSpan={10} className="bg-zinc-50 px-3 py-2 dark:bg-zinc-900">
                      <pre className="whitespace-pre-wrap font-mono text-[11px] text-red-700 dark:text-red-300">
                        {r.error_summary}
                      </pre>
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
