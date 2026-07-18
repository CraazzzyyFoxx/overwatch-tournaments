import type {
  EncounterMapPoolEntry,
  EncounterMapPoolState,
  MapVetoAction,
} from "@/types/tournament.types";

export type VetoSide = "home" | "away";
export type VetoStepAction = MapVetoAction | "decider";

export interface ParsedVetoStep {
  token: string;
  action: VetoStepAction;
  side: VetoSide | null;
}

/** Resolved sequence tokens are "ban_home" / "pick_away" / "decider". */
export function parseStepToken(token: string): ParsedVetoStep {
  if (token === "decider") {
    return { token, action: "decider", side: null };
  }
  const [action, side] = token.split("_");
  return {
    token,
    action: action === "pick" ? "pick" : "ban",
    side: side === "away" ? "away" : "home",
  };
}

/** Picked/played maps in their final play order (action_index, legacy `order` fallback). */
export function pickedMapsInOrder(pool: EncounterMapPoolEntry[]): EncounterMapPoolEntry[] {
  return pool
    .filter((entry) => entry.status === "picked" || entry.status === "played")
    .sort(
      (left, right) =>
        (left.action_index ?? left.order) - (right.action_index ?? right.order),
    );
}

/**
 * Epoch-ms deadline of the current turn, or null when the timer indicator
 * should not be shown (no timer configured, session inactive, veto complete).
 */
export function turnDeadlineMs(state: EncounterMapPoolState): number | null {
  const session = state.session;
  if (!session || session.status !== "active" || state.is_complete) return null;
  if (session.turn_timer_seconds == null || !session.current_step_started_at) return null;
  const startedAt = Date.parse(session.current_step_started_at);
  if (Number.isNaN(startedAt)) return null;
  return startedAt + session.turn_timer_seconds * 1000;
}
