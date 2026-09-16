import Link from "next/link";
import { Input, Select } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import type { PrizeCategory, SourceRow } from "@/lib/types";

const PRIZE_CATEGORIES: PrizeCategory[] = [
  "physical_good",
  "cash",
  "general_gift_card",
  "restricted_gift_card",
  "digital_game",
  "digital_good",
  "experience",
  "travel",
  "event_ticket",
  "service",
  "books_media",
  "discount",
  "subscription",
  "other",
  "unknown",
];

export function GiveawayFiltersBar({
  sources,
  entryMethods,
  values,
}: {
  sources: SourceRow[];
  entryMethods: string[];
  values: Record<string, string | undefined>;
}) {
  const wantedChecked = values.wanted !== "0";
  const franceChecked = values.france !== "0";
  const hideGoneChecked = values.hide_gone !== "0";

  return (
    <form className="grid grid-cols-2 gap-3 border-b border-zinc-200 p-4 md:grid-cols-4 xl:grid-cols-6 dark:border-zinc-800">
      <label className="block space-y-1.5">
        <span className="text-xs uppercase text-zinc-500">Search</span>
        <Input name="q" defaultValue={values.q ?? ""} placeholder="Title, prize, domain…" />
      </label>
      <label className="block space-y-1.5">
        <span className="text-xs uppercase text-zinc-500">Status</span>
        <Select name="status" defaultValue={values.status ?? "active"}>
          <option value="active">Active (default)</option>
          <option value="all">All statuses</option>
          <option value="expired">Expired</option>
        </Select>
      </label>
      <label className="block space-y-1.5">
        <span className="text-xs uppercase text-zinc-500">Manual status</span>
        <Select name="manual_status" defaultValue={values.manual_status ?? "all"}>
          <option value="all">Main view (hide ignored)</option>
          <option value="ignored">Ignored list</option>
          <option value="none">none</option>
          <option value="interested">interested</option>
          <option value="entered">entered</option>
          <option value="won">won</option>
          <option value="lost">lost</option>
        </Select>
      </label>
      <label className="block space-y-1.5">
        <span className="text-xs uppercase text-zinc-500">Source</span>
        <Select name="source_id" defaultValue={values.source_id ?? ""}>
          <option value="">All sources</option>
          {sources.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </Select>
      </label>
      <label className="block space-y-1.5">
        <span className="text-xs uppercase text-zinc-500">Prize category</span>
        <Select name="prize_category" defaultValue={values.prize_category ?? ""}>
          <option value="">All categories</option>
          {PRIZE_CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </Select>
      </label>
      <label className="block space-y-1.5">
        <span className="text-xs uppercase text-zinc-500">Entry method</span>
        <Select name="entry_method" defaultValue={values.entry_method ?? ""}>
          <option value="">All methods</option>
          {entryMethods.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </Select>
      </label>
      <label className="block space-y-1.5">
        <span className="text-xs uppercase text-zinc-500">Sort</span>
        <Select name="sort" defaultValue={values.sort ?? "priority"}>
          <option value="priority">Wanted / priority</option>
          <option value="newest">Newest</option>
          <option value="ending_soon">Ending soon</option>
          <option value="highest_value">Highest prize value</option>
          <option value="highest_confidence">Highest confidence</option>
        </Select>
      </label>
      <label className="block space-y-1.5">
        <span className="text-xs uppercase text-zinc-500">Min value €</span>
        <Input
          name="min_value"
          type="number"
          min={0}
          step={1}
          defaultValue={values.min_value ?? ""}
          placeholder="0"
        />
      </label>
      <label className="flex items-center gap-2.5 py-2 text-sm font-medium">
        <input type="hidden" name="wanted" value="0" />
        <input
          type="checkbox"
          name="wanted"
          value="1"
          defaultChecked={wantedChecked}
          className="h-4 w-4 rounded border-zinc-400"
        />
        Wanted only
      </label>
      <label className="flex items-center gap-2.5 py-2 text-sm font-medium">
        <input type="hidden" name="france" value="0" />
        <input
          type="checkbox"
          name="france"
          value="1"
          defaultChecked={franceChecked}
          className="h-4 w-4 rounded border-zinc-400"
        />
        France eligible
      </label>
      <label className="flex items-center gap-2.5 py-2 text-sm font-medium">
        <input type="hidden" name="hide_gone" value="0" />
        <input
          type="checkbox"
          name="hide_gone"
          value="1"
          defaultChecked={hideGoneChecked}
          className="h-4 w-4 rounded border-zinc-400"
        />
        Hide dead links
      </label>
      <label className="flex items-center gap-2.5 py-2 text-sm">
        <input
          type="checkbox"
          name="free"
          value="1"
          defaultChecked={values.free === "1"}
          className="h-4 w-4 rounded border-zinc-400"
        />
        Free only
      </label>
      <label className="flex items-center gap-2.5 py-2 text-sm">
        <input
          type="checkbox"
          name="ending_soon"
          value="1"
          defaultChecked={values.ending_soon === "1"}
          className="h-4 w-4 rounded border-zinc-400"
        />
        Ending soon
      </label>
      <label className="flex items-center gap-2.5 py-2 text-sm text-zinc-500">
        <input
          type="checkbox"
          name="show_unknown_france"
          value="1"
          defaultChecked={values.show_unknown_france === "1"}
          className="h-4 w-4 rounded border-zinc-400"
        />
        Inspect: FR unknown
      </label>
      <label className="flex items-center gap-2.5 py-2 text-sm text-zinc-500">
        <input
          type="checkbox"
          name="show_ineligible"
          value="1"
          defaultChecked={values.show_ineligible === "1"}
          className="h-4 w-4 rounded border-zinc-400"
        />
        Inspect: FR ineligible
      </label>
      <label className="flex items-center gap-2.5 py-2 text-sm text-zinc-500">
        <input
          type="checkbox"
          name="show_unwanted"
          value="1"
          defaultChecked={values.show_unwanted === "1"}
          className="h-4 w-4 rounded border-zinc-400"
        />
        Inspect: unwanted prizes
      </label>
      <div className="flex items-end gap-3">
        <Button type="submit" size="md">
          Apply
        </Button>
        <Link href="/giveaways" className="text-sm text-zinc-500 hover:underline">
          Reset
        </Link>
      </div>
    </form>
  );
}
