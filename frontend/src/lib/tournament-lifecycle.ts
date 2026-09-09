import type { TournamentStatus } from "@/types/tournament.types";

/**
 * The tournament lifecycle machine, mirrored from
 * `backend/shared/core/tournament_state.py`.
 *
 * One copy for the whole frontend. The phase order, the legal transitions, the
 * schedulable phases and the admin-facing labels each used to be re-typed in a
 * different file — the status picker, the hub stepper, the living checklist,
 * the public phase timeline, the settings form and the creation wizard — so a
 * status could be offered by the picker while the stepper had never heard of
 * it, and nothing failed until someone looked at the screen.
 *
 * `tournament-lifecycle.parity.test.ts` reads the Python module and fails on
 * drift; a hand-mirrored constant with no such test is a rumour.
 */

/** Canonical machine order (`PHASE_ORDER`). Automation only moves forward along it. */
export const TOURNAMENT_PHASES = [
  "announcement",
  "registration",
  "check_in",
  "draft",
  "live",
  "playoffs",
  "completed",
  "archived"
] as const satisfies readonly TournamentStatus[];

/**
 * Phases that may carry a `tournament_phase_schedule` row (`SCHEDULABLE_STATUSES`).
 * Playoffs onward depend on the actual course of play and are never scheduled.
 */
export const SCHEDULABLE_PHASES = ["registration", "check_in", "draft", "live"] as const;

export type SchedulablePhase = (typeof SCHEDULABLE_PHASES)[number];

/**
 * `_VALID_TRANSITIONS`: forward edges allow phase skips, back edges reach the
 * prior effective phases so an admin can reopen registration without `force`.
 * Anything outside this map needs `force`, which the server accepts from a
 * superuser only.
 */
export const VALID_TRANSITIONS: Record<TournamentStatus, readonly TournamentStatus[]> = {
  announcement: ["registration", "check_in", "draft", "live"],
  registration: ["check_in", "draft", "live", "announcement"],
  check_in: ["draft", "live", "registration"],
  draft: ["live", "check_in", "registration"],
  live: ["playoffs", "completed", "draft", "check_in"],
  playoffs: ["completed"],
  completed: ["archived"],
  archived: ["completed"]
};

/**
 * Admin-surface labels. The public site translates instead
 * (`common.statusBadge.<status>`); the hub is English-only.
 */
export const TOURNAMENT_STATUS_LABELS: Record<TournamentStatus, string> = {
  announcement: "Announcement",
  registration: "Registration",
  check_in: "Check-in",
  draft: "Draft",
  live: "Live",
  playoffs: "Playoffs",
  completed: "Completed",
  archived: "Archived"
};

const PHASE_RANK = Object.fromEntries(
  TOURNAMENT_PHASES.map((status, index) => [status, index])
) as Record<TournamentStatus, number>;

/** Position in the machine order. Higher means later in the tournament's life. */
export function phaseRank(status: TournamentStatus): number {
  return PHASE_RANK[status];
}

/** Whether the tournament is at or past `target`. */
export function reachedAtLeast(status: TournamentStatus, target: TournamentStatus): boolean {
  return phaseRank(status) >= phaseRank(target);
}

export function isSchedulablePhase(value: string): value is SchedulablePhase {
  return (SCHEDULABLE_PHASES as readonly string[]).includes(value);
}
