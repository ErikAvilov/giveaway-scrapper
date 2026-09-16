import { SourcesTable } from "@/components/sources/table";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { listSources } from "@/server/queries";

export const dynamic = "force-dynamic";

export default async function SourcesPage() {
  let error: string | null = null;
  let sources: Awaited<ReturnType<typeof listSources>> = [];
  try {
    sources = await listSources();
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load sources";
  }

  return (
    <div className="space-y-3 p-4">
      <header>
        <h1 className="text-base font-semibold">Sources</h1>
        <p className="text-xs text-zinc-500">
          Enable/disable crawlers and adjust intervals. No shell/SQL tooling here.
        </p>
      </header>
      {error ? (
        <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-800">
          {error}
        </div>
      ) : null}
      <Panel>
        <PanelHeader title="Configured sources" description={`${sources.length} total`} />
        <SourcesTable sources={sources} />
      </Panel>
    </div>
  );
}
