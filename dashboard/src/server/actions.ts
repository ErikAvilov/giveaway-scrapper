"use server";

import { revalidatePath } from "next/cache";
import {
  clearGiveawayReminder,
  setGiveawayReminder,
  setSourceEnabled,
  setSourceInterval,
  updateManualStatus,
} from "@/server/queries";
import type { ManualStatus } from "@/lib/types";

export async function updateGiveawayManualStatusAction(
  giveawayId: string,
  manualStatus: ManualStatus,
) {
  await updateManualStatus(giveawayId, manualStatus);
  revalidatePath("/giveaways");
  revalidatePath("/");
  revalidatePath(`/giveaways/${giveawayId}`);
}

export async function setGiveawayReminderAction(
  giveawayId: string,
  hours: number,
) {
  await setGiveawayReminder(giveawayId, hours);
  revalidatePath("/giveaways");
  revalidatePath("/");
  revalidatePath(`/giveaways/${giveawayId}`);
}

export async function clearGiveawayReminderAction(giveawayId: string) {
  await clearGiveawayReminder(giveawayId);
  revalidatePath("/giveaways");
  revalidatePath("/");
  revalidatePath(`/giveaways/${giveawayId}`);
}

export async function toggleSourceEnabledAction(sourceId: string, enabled: boolean) {
  await setSourceEnabled(sourceId, enabled);
  revalidatePath("/sources");
}

export async function updateSourceIntervalAction(
  sourceId: string,
  intervalMinutes: number,
) {
  await setSourceInterval(sourceId, intervalMinutes);
  revalidatePath("/sources");
}
