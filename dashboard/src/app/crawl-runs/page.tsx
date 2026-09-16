import { CrawlRunsTable } from "@/components/crawl-runs/table";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { listCrawlRuns } from "@/server/queries";

export const dynamic = "force-dynamic";

export default async function CrawlRunsPage() {
  let error: string | null = null;
  let runs: Awaited<ReturnType<typeof listCrawlRuns>> = [];
  try {
    runs = await listCrawlRuns(100);
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load crawl runs";
  }

  return (
    <div className="space-y-3 p-4">
      <header>
        <h1 className="text-base font-semibold">Crawl runs</h1>
        <p className="text-xs text-zinc-500">Execution history from the Raspberry Pi collector</p>
      </header>
      {error ? (
        <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-800">
          {error}
        </div>
      ) : null}
      <Panel>
        <PanelHeader title="Recent runs" description={`${runs.length} shown`} />
        <CrawlRunsTable runs={runs} />
      </Panel>
    </div>
  );
}
