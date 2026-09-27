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

/** Whether a bigger value of a column is the better one. */
export type FfaColumnBetter = "higher" | "lower";

/**
 * One value the organizer records per team per game: kills, deaths, damage, a
 * penalty. The key is what the stage's formula reads; the label is the only
 * thing ever printed, so the table never invents a word for a column.
 */
export interface FfaColumn {
  key: string;
  label: string;
  /** `false` — the column exists only for the organizer. A public read drops
   *  the column AND its values, so a `false` here can only arrive through the
   *  admin read. */
  public: boolean;
  better: FfaColumnBetter;
}

/** The stage's `ffa_scoring`, resolved for this lobby. */
export interface FfaRules {
  columns: FfaColumn[];
  /** Points for placing 1st, 2nd, … A shorter list scores the tail at zero. */
  placement_points: number[];
  /** The organizer's expression over the column keys, `place`, `place_pts` and
   *  `teams`. Shown as the rule the table is scored by; never evaluated here —
   *  the points on the wire are the server's (spec §11). */
  formula: string;
  /** The formula reads the place, so a game cannot be recorded without a full
   *  permutation of 1..N. Derived server-side from the formula, never a flag
   *  the organizer can desync from it. */
  requires_placement: boolean;
}

export interface FfaGameCell {
  position: number;
  /** `null` — the game has not been opened yet. */
  state: EncounterGameState | null;
  placement: number | null;
  points: number | null;
  /** What was entered for this game, by column key. `null` — nobody has played
   *  it; `{}` is a played game whose stage has no columns. A key missing from a
   *  played game scores zero (spec §3.2). */
  stats: Record<string, number> | null;
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
  /** Each column summed over the games played. A key the team never scored is
   *  absent, not zero. */
  stats: Record<string, number>;
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

/** One team's line of a game result. `placement` is null when the stage's
 *  formula does not read the place, and the server derives it from the points. */
export interface FfaGameResultLineInput {
  team_id: number;
  placement?: number | null;
  /** Exactly the stage's column keys — the server rejects a missing one
   *  (`ffa_result_missing_stat`) and an extra one (`ffa_result_unknown_stat`). */
  stats: Record<string, number>;
}

export interface FfaGameResultsInput {
  results: FfaGameResultLineInput[];
  /** Required by the server when it overwrites an already-confirmed game. */
  reason?: string | null;
}
