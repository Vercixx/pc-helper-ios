/**
 * How a PC's state looks: one SF Symbol and one colour, shared by the list row
 * and the detail screen so the two can never disagree about what "asleep" means.
 */

import type { PCStatusSnapshot } from "@/state/types";
import { statusColors } from "@/ui/theme";

export function statusSymbol(status: PCStatusSnapshot | undefined) {
  if (!status || !status.reachable) return "moon.zzz.fill" as const;
  return status.locked ? ("lock.fill" as const) : ("desktopcomputer" as const);
}

export function statusColor(status: PCStatusSnapshot | undefined): string {
  if (!status || !status.reachable) return statusColors.unknown;
  return status.locked ? statusColors.locked : statusColors.unlocked;
}
