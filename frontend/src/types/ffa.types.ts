import type { EncounterGameState, EncounterResultStatus } from "@/types/tournament.types";

/**
 * The FFA lobby read model, mirroring `backend/tournament-service/src/schemas/ffa.py`.
 *
 * One shape serves both public endpoints — a stage answers a list of lobbies
 * and a single lobby answers one of them — so the lobby table renders from the
 * same model either way (docs/plans/2026-09-24-ffa-encounters.md §6).
 *
 * Nulls carry meaning and are never dropped on the wire: a cell with no `state`
 * is a game nobody has entered yet, and a row with no `position` is a group the
 * standings job has not ranked once.
 */

/** The stage's `ffa_scoring`, resolved for this lobby. */
export interface FfaRules {
  /** Points for placing 1st, 2nd, … A shorter list scores the tail at zero. */
  placement_points: number[];
  /** Multiplier applied to a team's raw score in a game. */
  score_points: number;
  /** What the score column counts ("Kills", "Points", …); `null` hides it. */
  score_label: string | null;
}

export interface FfaGameCell {
  position: number;
  /** `null` — the game has not been opened yet. */
  state: EncounterGameState | null;
  placement: number | null;
  score: number | null;
  points: number | null;
}

export interface FfaLobbyRow {
  team_id: number;
  team_name: string;
  team_image_url: string | null;
  slot: number;
  /** `Standing.position` — the number advancement reads. `null` until the
   *  standings job has ranked the group once. */
  position: number | null;
  tie_group: number | null;
  /** The organizer pinned `position`; results no longer move it. */
  is_pinned: boolean;
  points: number;
  games_played: number;
  wins: number;
  score: number;
  games: FfaGameCell[];
}

export interface FfaLobby {
  encounter_id: number;
  tournament_id: number;
  stage_id: number | null;
  stage_item_id: number | null;
  name: string;
  status: string;
  result_status: EncounterResultStatus;
  best_of: number;
  scheduled_at: string | null;
  /** Item override, else the stage's number; `null` draws no cut line. */
  advance_count: number | null;
  rules: FfaRules;
  rows: FfaLobbyRow[];
}

/** One team's line of a game result. `placement` is null on a score-only lobby. */
export interface FfaGameResultLineInput {
  team_id: number;
  placement?: number | null;
  score: number;
}

export interface FfaGameResultsInput {
  results: FfaGameResultLineInput[];
  /** Required by the server when it overwrites an already-confirmed game. */
  reason?: string | null;
}
