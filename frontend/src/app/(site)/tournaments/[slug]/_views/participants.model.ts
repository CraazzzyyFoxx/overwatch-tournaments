import { formationModes } from "@/lib/tournament/flow-nodes";
import type { RegistrationStatus } from "@/types/registration.types";
import type { Tournament } from "@/types/tournament.types";

import { IDENTITY_EXTRAS_COLUMN_ID } from "./_components/participantsColumns.model";

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

/** The tournament has a formation whose roster is a player pool (balancer or draft) rather than a list of teams. */
export function hasPoolFormation(tournament: Pick<Tournament, "flow_nodes">): boolean {
  const modes = formationModes(tournament);
  return modes.has("balancer") || modes.has("draft");
}

/** Organizer-only columns: the player's notes and their extra BattleTags —
 *  what the roster shows ABOUT a player rather than the state of their own
 *  entry. Filtered out of the column CONFIG rather than blanked per cell, so
 *  they leave the table, the search and the column picker together.
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
  [IDENTITY_EXTRAS_COLUMN_ID]: true
};
