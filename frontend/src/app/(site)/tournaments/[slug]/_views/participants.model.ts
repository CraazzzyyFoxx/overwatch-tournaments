import type { Registration, RegistrationStatus } from "@/types/registration.types";

import type { ColumnDefinition } from "./_components/participantsColumns.model";

export type StatusFilter = "all" | RegistrationStatus;

/** Tint for a built-in status chip. A custom status brings its own colour on
 *  `status_meta` and never reads this table. */
export const STATUS_FILTER_META: Record<RegistrationStatus, { dot: string }> = {
  approved: { dot: "var(--aqt-emerald)" },
  pending: { dot: "var(--aqt-amber)" },
  insufficient_data: { dot: "var(--aqt-amber)" },
  rejected: { dot: "var(--aqt-rose)" },
  banned: { dot: "var(--aqt-rose)" },
  withdrawn: { dot: "var(--aqt-fg-dim)" }
};

export const STATUS_FILTER_ORDER: RegistrationStatus[] = [
  "approved",
  "pending",
  "insufficient_data",
  "rejected",
  "banned",
  "withdrawn"
];

// localeKeyMap removed to support DB status names without hardcoded translation

/** Statuses that permanently take the registration out of the tournament. */
export const TERMINAL_REGISTRATION_STATUSES = new Set<string>([
  "rejected",
  "banned",
  "withdrawn"
]);

/** Team formations whose roster is a player pool rather than a list of teams. */
export const POOL_TEAM_FORMATIONS: Record<string, true> = { balancer: true, draft: true };

/** Organizer-only columns: the player's notes and smurf tags — what the roster
 *  shows ABOUT a player rather than the state of their own entry. Filtered out
 *  of the column CONFIG rather than blanked per cell, so they leave the table,
 *  the search and the column picker together.
 *
 *  This is a roster-surface decision on top of the schema's `visibility`, which
 *  the server already enforces: an organizers-only answer never reaches a
 *  public read at all, and its column is skipped for want of a value.
 *
 *  Check-in, the subscription verdict and the balancer status are deliberately
 *  NOT here: all three are the registration's own public state — "am I in, and
 *  what is still missing" is the question this section is opened with, and the
 *  public read already ships `checked_in`, `subscription_outcome`, `admission`
 *  and `balancer_status` on every row. */
export const ADMIN_ONLY_COLUMN_IDS: Record<string, true> = {
  public_notes: true,
  smurf_tags: true
};

/** How many rows each status holds, for the filter chips' counts. */
export function countRegistrationStatuses(
  registrations: readonly Registration[]
): Partial<Record<RegistrationStatus, number>> {
  const counts: Partial<Record<RegistrationStatus, number>> = {};
  for (const reg of registrations) {
    counts[reg.status] = (counts[reg.status] ?? 0) + 1;
  }
  return counts;
}

/**
 * The statuses actually present in the data, built-in ones in their canonical
 * order first and the organizer's own custom statuses alphabetically after.
 */
export function orderPresentStatuses(
  registrations: readonly Registration[]
): RegistrationStatus[] {
  // Collect all unique statuses actually present in registrations
  const uniqueStatuses = Array.from(new Set(registrations.map((r) => r.status)));

  // Sort them so that built-in ones in STATUS_FILTER_ORDER come first, and any others (custom) come after
  return uniqueStatuses.sort((a, b) => {
    const idxA = STATUS_FILTER_ORDER.indexOf(a);
    const idxB = STATUS_FILTER_ORDER.indexOf(b);

    if (idxA !== -1 && idxB !== -1) {
      return idxA - idxB;
    }
    if (idxA !== -1) return -1;
    if (idxB !== -1) return 1;

    // Both are custom, sort alphabetically
    return a.localeCompare(b);
  });
}

/** Chip label and dot colour per status, resolved from the first row that
 *  carries it — the server sends the custom status' own name and colour. */
export function buildStatusMetaMap(
  registrations: readonly Registration[]
): Record<string, { name: string; dot: string }> {
  const map: Record<string, { name: string; dot: string }> = {};
  for (const reg of registrations) {
    if (!map[reg.status]) {
      // Resolve name: prefer status_meta.name, fallback to humanized value
      let name = reg.status_meta?.name ?? reg.status;
      if (name === reg.status) {
        name = name.charAt(0).toUpperCase() + name.slice(1).replace(/_/g, " ");
      }

      // Resolve dot color: prefer status_meta.icon_color, fallback to STATUS_FILTER_META, fallback to gray
      let dot = reg.status_meta?.icon_color ?? "";
      if (!dot) {
        dot = STATUS_FILTER_META[reg.status as RegistrationStatus]?.dot ?? "var(--aqt-fg-dim)";
      }

      map[reg.status] = { name, dot };
    }
  }
  return map;
}

/** Status filter + dynamic search across all searchable columns. */
export function filterRegistrations(
  registrations: Registration[],
  statusFilter: StatusFilter,
  searchQuery: string,
  visibleColumns: readonly ColumnDefinition[]
): Registration[] {
  const byStatus =
    statusFilter === "all"
      ? registrations
      : registrations.filter((r) => r.status === statusFilter);

  if (!searchQuery.trim()) return byStatus;
  const q = searchQuery.trim().toLowerCase();
  return byStatus.filter((r) =>
    visibleColumns.some((col) => {
      if (!col.searchValue) return false;
      const val = col.searchValue(r);
      return val?.toLowerCase().includes(q) ?? false;
    })
  );
}
