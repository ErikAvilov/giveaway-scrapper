import { Badge } from "@/components/ui/badge";
import type { GiveawayRow } from "@/lib/types";
import { formatRelativeHours } from "@/lib/utils";

function endingSoon(g: GiveawayRow): boolean {
  if (!g.end_at) return false;
  const ms = g.end_at.getTime() - Date.now();
  return ms >= 0 && ms <= 7 * 24 * 60 * 60 * 1000;
}

export function GiveawayBadges({ giveaway }: { giveaway: GiveawayRow }) {
  return (
    <div className="flex flex-wrap gap-1">
      {giveaway.wanted_prize === true ? <Badge variant="free">Wanted</Badge> : null}
      {giveaway.wanted_prize === false ? <Badge variant="muted">Unwanted</Badge> : null}
      {giveaway.prize_priority != null ? (
        <Badge variant="default">P{giveaway.prize_priority}</Badge>
      ) : null}
      {giveaway.requires_travel ? <Badge variant="warn">Travel</Badge> : null}
      {giveaway.requires_additional_spend ? (
        <Badge variant="purchase">Extra spend</Badge>
      ) : null}
      {giveaway.eligible_france ? <Badge variant="france">France</Badge> : null}
      {giveaway.free_entry ? <Badge variant="free">Free</Badge> : null}
      {giveaway.requires_purchase ? <Badge variant="purchase">Purchase</Badge> : null}
      {giveaway.requires_social ? <Badge variant="social">Social</Badge> : null}
      {giveaway.requires_public_social_action || giveaway.entry_acceptable === false ? (
        <Badge variant="danger">Public social action</Badge>
      ) : null}
      {giveaway.reminder_due ? (
        <Badge variant="warn">Rappel dû · {formatRelativeHours(giveaway.remind_at)}</Badge>
      ) : giveaway.remind_at ? (
        <Badge variant="default">Rappel · {formatRelativeHours(giveaway.remind_at)}</Badge>
      ) : null}
      {endingSoon(giveaway) && giveaway.status !== "expired" ? (
        <Badge variant="warn">Ending soon</Badge>
      ) : null}
      {giveaway.status === "expired" ? <Badge variant="danger">Expired</Badge> : null}
      {giveaway.status === "uncertain" ? <Badge variant="muted">Uncertain</Badge> : null}
      {giveaway.status === "rejected" ? <Badge variant="muted">Rejected</Badge> : null}
      {giveaway.status === "active" ? <Badge variant="free">Active</Badge> : null}
      {giveaway.status === "candidate" ? <Badge variant="default">Candidate</Badge> : null}
    </div>
  );
}
