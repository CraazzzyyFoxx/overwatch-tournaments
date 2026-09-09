// Live Draft types — mirror the balancer-service DTOs (src/schemas/draft.py).

import type { RosterRoleSlotCode, RosterShape, RosterSlotCode } from "@/lib/roster-shape";
import type { CustomFieldDefinition } from "@/types/registration.types";

export type DraftStatus = "setup" | "ready" | "live" | "paused" | "completed" | "cancelled";

export type DraftFormat = "snake" | "linear" | "custom";
type DraftPoolSource = "balancer_balance" | "manual";
export type DraftAutopickStrategy = "best_fit" | "best_available" | "role_need";
export type DraftRole = RosterRoleSlotCode;
type DraftPlayerStatus = "available" | "picked" | "removed";
export type DraftPickStatus = "upcoming" | "on_clock" | "completed" | "skipped" | "autopicked";

export interface DraftSession {
  id: number;
  tournament_id: number;
  workspace_id: number;
  status: DraftStatus;
  blocked_reason: string | null;
  format: DraftFormat;
  rounds: number;
  pick_time_seconds: number;
  // The shape the session was created with. There is no `team_size` field: the
  // server resolves the shape and every derived number lives on it.
  roster_shape: RosterShape;
  current_pick_id: number | null;
  pool_source: DraftPoolSource;
  source_balance_id: number | null;
  autopick_strategy: DraftAutopickStrategy;
  allow_admin_override: boolean;
  exported_at: string | null;
  export_status: string | null;
  settings_json: Record<string, any>;
  version: number;
  /** Null only for a session the server has not persisted yet. */
  created_at: string | null;
}

export interface DraftTeam {
  id: number;
  session_id: number;
  captain_user_id: number | null;
  captain_auth_user_id: number | null;
  name: string;
  draft_position: number;
  exported_team_id: number | null;
}

/** One organizer-approved registration answer, ready to render in the inspector.
 *  Only definitions flagged `show_in_draft` on the registration form reach the
 *  public board, and the server sends the definition's CURRENT label/type with
 *  each value so the draft client needs no form config of its own. */
interface DraftPlayerCustomField {
  key: string;
  label: string;
  type: CustomFieldDefinition["type"];
  value: unknown;
}

/** Where a role's resolved rank came from — mirrors `shared.domain.roster.RankSource`. */
export type DraftRankSource = "registration" | "workspace" | "ow" | "none";

export interface DraftPlayer {
  id: number;
  session_id: number;
  registration_id: number;
  user_id: number | null;
  battle_tag: string | null;
  /**
   * `null` when the player has no playable role left — an organizer can strip
   * every rank mid-draft. Render that as "no role", never as a default one.
   */
  primary_role: DraftRole | null;
  sub_role: string | null;
  is_flex: boolean;
  /**
   * Server-resolved: the ONE rank that represents this player in THIS draft.
   * Their primary role's rank under a shape with role slots, their best role
   * rank under a role-less (all-flex) one, where nobody is assigned a role.
   * The rule lives once, in the roster engine.
   */
  effective_rank: number | null;
  status: DraftPlayerStatus;
  is_captain: boolean;
  drafted_by_team_id: number | null;
  secondary_roles: string[];
  role_ranks: Record<string, number>;
  /** Per-role provenance of `role_ranks`, keyed the same way. */
  role_sources: Record<string, DraftRankSource>;
  role_top_heroes: Record<string, Array<string | { slug: string; image_path: string | null }>>;
  notes: string | null;
  custom_fields: DraftPlayerCustomField[];
  version: number;
}

export interface DraftPick {
  id: number;
  session_id: number;
  overall_no: number;
  round_no: number;
  pick_in_round: number;
  draft_team_id: number;
  target_role: DraftRole | null;
  target_rank_value: number | null;
  status: DraftPickStatus;
  picked_player_id: number | null;
  picked_by_user_id: number | null;
  is_autopick: boolean;
  is_admin_override: boolean;
  clock_started_at: string | null;
  clock_expires_at: string | null;
  version: number;
}

export interface DraftBoard {
  session: DraftSession;
  teams: DraftTeam[];
  picks: DraftPick[];
  players: DraftPlayer[]; // all pool players; derive availability + rosters client-side
  current_pick: DraftPick | null;
  server_time: string;
  last_event_id: number | null;
}

interface DraftSuggestion {
  player_id: number;
  role: DraftRole;
  fit_score: number;
  breakdown: Record<string, number>;
}

export interface DraftSuggestionsResponse {
  pick_id: number;
  draft_team_id: number;
  suggestions: DraftSuggestion[];
}

// The server declares `slot_code` as a plain string, but the value set is closed:
// `shared.domain.roster_shape` rejects anything outside `ROSTER_SLOT_CODES`. The
// narrower type is what lets these codes index role-keyed lookups and message
// keys without a cast.
interface DraftSlot {
  team_id: number;
  slot_code: RosterSlotCode;
  ordinal: number;
}

interface DraftSlotDeficit {
  slot_code: RosterSlotCode;
  unmatched_slots: number;
  eligible_players: number;
}

export interface DraftFeasibility {
  is_feasible: boolean;
  total_open_slots: number;
  matched_slots: number;
  unmatched_slots: DraftSlot[];
  slot_deficits: DraftSlotDeficit[];
  blocking_player_ids: number[];
  reason_code: string | null;
}

export interface DraftPickOption {
  player_id: number;
  role: DraftRole;
  is_safe: boolean;
  reason_code: string | null;
  unmatched_slots: DraftSlot[];
  blocking_player_ids: number[];
  suggestion_score: number | null;
}

export interface DraftPickOptionsResponse {
  pick_id: number;
  pick_version: number;
  draft_team_id: number;
  options: DraftPickOption[];
}

export interface DraftPresenceState {
  users: Record<number, { last_active_at: string }>;
  anonymous_viewer_count: number;
}

export interface DraftEventData {
  session_id: number;
  status?: DraftStatus;
  pick_id?: number;
  overall_pick_no?: number;
  draft_team_id?: number;
  picked_player_id?: number | null;
  current_pick_index?: number | null;
  clock_expires_at?: string | null;
  remaining_ms?: number;
  count_bucket?: string;
  /** Cache-scoping hint stamped by the publisher (`draft_progress`), NOT a
   *  business reason — see backend draft/realtime.py. */
  reason?: string;
  /** Why the draft paused, on `draft.blocked`. */
  blocked_reason?: string;
  /** Why an autopick fired, on `draft.autopicked`. Informational. */
  autopick_reason?: string;
  target_role?: DraftRole | null;
  target_rank_value?: number | null;
  pick_version?: number;
  player_id?: number;
  player_version?: number;
  is_feasible?: boolean;
  user_ids?: number[];
  anonymous_viewer_count?: number;
  [key: string]: unknown;
}

// Request bodies.
export interface DraftSessionCreateRequest {
  pool_source?: DraftPoolSource;
  source_balance_id?: number | null;
  format?: DraftFormat;
  pick_time_seconds?: number;
  autopick_strategy?: DraftAutopickStrategy;
  allow_admin_override?: boolean;
  settings?: Record<string, unknown>;
}

interface DraftPoolCaptainInput {
  registration_id: number;
  name?: string | null;
}

export type DraftCaptainOrder = "manual" | "weakest_first" | "strongest_first" | "random";

export interface DraftSeedRequest {
  source_balance_id?: number | null;
  seed?: number | null;
  // Seat order for captains (who picks first).
  captain_order?: DraftCaptainOrder;
  // Preferred: captains chosen from the existing balancer pool.
  pool_captains?: DraftPoolCaptainInput[];
  // Captains are the only seed input: the pool itself comes from the
  // tournament's registrations, resolved server-side.
  preview_only?: boolean;
  expected_version?: number | null;
}

interface DraftSeedDiff {
  teams_before: number;
  teams_after: number;
  players_before: number;
  players_after: number;
  picks_before: number;
  picks_after: number;
  session_version_before: number;
  session_version_after: number;
}

export interface DraftSeedResponse {
  session: DraftSession;
  preview_only: boolean;
  diff: DraftSeedDiff;
  feasibility: DraftFeasibility;
}

export interface DraftRoleEditRequest {
  role: DraftRole;
  /**
   * REQUIRED and positive. A rankless role is not playable, so adding one used
   * to create a role the draft would never offer; the server dropped the
   * "confirm there is no rank" escape hatch along with it.
   */
  rank_value: number;
  reason: string;
  expected_version: number;
  preview_only?: boolean;
}

export interface DraftRoleEditResponse {
  player_id: number;
  role: DraftRole;
  player_version: number;
  committed: boolean;
  before: DraftFeasibility;
  after: DraftFeasibility;
}
