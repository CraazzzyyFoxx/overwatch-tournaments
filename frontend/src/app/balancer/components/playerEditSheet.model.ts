import type { PlayerRankHistoryPreview, PlayerRankHistoryPreviewEntry } from "@/components/balancer/workspace-helpers";
import type { BalancerPlayerRoleEntry, BalancerRoleCode } from "@/types/balancer-admin.types";

export const ROLE_OPTIONS: Array<{ value: BalancerRoleCode; label: string }> = [
  { value: "tank", label: "Tank" },
  { value: "damage", label: "Damage" },
  { value: "support", label: "Support" }
];

export const ROLE_DISPLAY: Record<BalancerRoleCode, string> = {
  tank: "Tank",
  damage: "Damage",
  support: "Support"
};

/** Which workspaces the "Load from history" preview reads, remembered per browser. */
export const MULTIPLE_WORKSPACES_COOKIE = "aqt-history-multiple-workspaces";

/** One entry per role, in priority order, with `priority` renumbered from that
 *  order — the array position is what the balancer reads. */
export function normalizeRoleEntries(
  entries: BalancerPlayerRoleEntry[]
): BalancerPlayerRoleEntry[] {
  const seen = new Set<BalancerRoleCode>();
  const sorted = [...entries].sort((a, b) => a.priority - b.priority);
  const normalized: BalancerPlayerRoleEntry[] = [];

  for (const entry of sorted) {
    if (seen.has(entry.role)) continue;
    seen.add(entry.role);
    normalized.push({
      role: entry.role,
      subtype: entry.subtype ?? null,
      priority: normalized.length + 1,
      division_number: entry.division_number ?? null,
      rank_value: entry.rank_value,
      is_active: entry.is_active ?? false,
      is_declared_active: entry.is_declared_active ?? true,
      ow_rank_value: entry.ow_rank_value ?? null,
      rank_source: entry.rank_source
    });
  }

  return normalized;
}

export function applyHistoryToSelectedRoles(
  entries: BalancerPlayerRoleEntry[],
  history: Partial<Record<BalancerRoleCode, number>> | null,
  resolveDivision: (rankValue: number | null) => number | null
): BalancerPlayerRoleEntry[] {
  if (!history) {
    return entries;
  }

  return normalizeRoleEntries(
    entries.map((entry) => {
      const rankValue = history[entry.role];
      if (rankValue == null) {
        return entry;
      }

      return {
        ...entry,
        rank_value: rankValue,
        division_number: resolveDivision(rankValue)
      };
    })
  );
}

export function applyHistoryPreviewToRoleEntries(
  entries: BalancerPlayerRoleEntry[],
  preview: PlayerRankHistoryPreview | null,
  resolveRankFromDivision: (divisionNumber: number | null) => number | null
): BalancerPlayerRoleEntry[] {
  if (!preview || preview.entries.length === 0) {
    return entries;
  }

  const byRole = new Map(entries.map((entry) => [entry.role, entry]));
  for (const historyEntry of preview.entries) {
    const existingEntry = byRole.get(historyEntry.role);
    // Only fill ranks for roles the player already has in the balancer; never add
    // new roles from history — applying history must not change the player's roles.
    if (!existingEntry) {
      continue;
    }

    // Use the normalised division to derive a rank_value in the target grid,
    // so that the form's rank/division fields stay consistent.
    const normalizedRank =
      resolveRankFromDivision(historyEntry.division_number) ?? historyEntry.rank_value;
    byRole.set(historyEntry.role, {
      ...existingEntry,
      rank_value: normalizedRank,
      division_number: historyEntry.division_number,
      // Applying history both enables the role and gives it a rank, so it is
      // declared on AND in play.
      is_active: true,
      is_declared_active: true
    });
  }

  return normalizeRoleEntries(Array.from(byRole.values()));
}

export function buildHistoryChangeText(
  currentEntry: BalancerPlayerRoleEntry | undefined,
  historyEntry: PlayerRankHistoryPreviewEntry
): string {
  if (!currentEntry) {
    return `Will add this role with ${historyEntry.rank_value}.`;
  }

  if (currentEntry.rank_value == null) {
    return `Will set ${historyEntry.rank_value} on the existing role.`;
  }

  if (currentEntry.rank_value === historyEntry.rank_value) {
    return `Matches the current SR (${currentEntry.rank_value}).`;
  }

  return `Current ${currentEntry.rank_value} -> new ${historyEntry.rank_value}.`;
}

/**
 * `ready`/`incomplete` are computed server-side from role ranks the moment
 * roles are saved (see `sync_included_balancer_status`) — nothing here mirrors
 * that. This only drives the read-only "computed" preview badge.
 */
export function isComputedReady(entries: BalancerPlayerRoleEntry[]): boolean {
  const activeRoles = entries.filter((entry) => entry.is_active);
  return (
    activeRoles.length > 0 &&
    activeRoles.every(
      (entry) =>
        entry.rank_value !== null &&
        entry.rank_value !== undefined &&
        String(entry.rank_value).trim() !== ""
    )
  );
}
