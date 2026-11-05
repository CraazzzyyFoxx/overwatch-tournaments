import { TOURNAMENT_PHASES, phaseRank } from "@/lib/tournament/lifecycle";
import type { TournamentStatus } from "@/types/tournament.types";

/**
 * The status chain for the hub stepper (design D19): the derived statuses in order, minus Archived. Archiving is
 * bookkeeping after the end, not a phase with work in it, so the chain stops at Completed and an archived tournament
 * reads as a completed one.
 */

export interface EffectivePhase {
  key: TournamentStatus;
  /** Phase is at or before the tournament's current status. */
  reached: boolean;
}

export function effectivePhases(currentStatus?: TournamentStatus): EffectivePhase[] {
  const position = currentStatus === "archived" ? "completed" : currentStatus;
  const currentOrder = position === undefined ? -1 : phaseRank(position);

  return TOURNAMENT_PHASES.filter((key) => key !== "archived").map((key) => ({
    key,
    reached: currentOrder >= 0 && phaseRank(key) <= currentOrder
  }));
}
