// Live Draft types — mirror the balancer-service DTOs (src/schemas/draft.py).

import type { RosterShape, SlotCode } from "@/lib/roster/shape";
import type { FormField } from "@/types/forms.types";
import type { RoleRef } from "@/lib/roster/role-ref";
import type { PlayerIdentity } from "@/types/identity.types";

export type DraftStatus = "setup" | "ready" | "live" | "paused" | "completed" | "cancelled";

export type DraftFormat = "snake" | "linear" | "custom";

/**
 * The tournament's draft format rule (`Tournament.draft_format_json`); `null` on
 * the tournament = snake. Normalized server-side: only `custom` keeps rules.
 */
export interface DraftFormatSettings {
  format: DraftFormat;
  round_rules: string[];
  avg_tie_seed_reverse: boolean;
}
type DraftPoolSource = "balancer_balance" | "manual";
export type DraftAutopickStrategy = "best_fit" | "best_available" | "role_need";
/** A role code of the session's owner game (its rated dimension): the vocabulary is the game's, never a fixed list. */
export type DraftRole = string;
type DraftPlayerStatus = "available" | "picked" | "removed";
export type DraftPickStatus = "upcoming" | "on_clock" | "completed" | "skipped" | "autopicked";

/** A session's lifecycle verbs, for a tournament's draft and a mix lobby's alike. */
export type DraftLifecycleAction = "start" | "pause" | "resume" | "cancel" | "rollback";

export interface DraftSession {
  id: number;
  tournament_id: number | null;
  /** The mix owning this draft and its lobby (0 = A); both null for a tournament's draft (spec §9.1). */
  custom_game_id: number | null;
  lobby_index: number | null;
  workspace_id: number;
  /** The owner's discipline (owner context for catalog/ontology/identity reads). */
  discipline: string;
  status: DraftStatus;
  blocked_reason: string | null;
  format: DraftFormat;
  rounds: number;
  pick_time_seconds: number;
  /**
   * Extra seconds a pick gets AFTER its main clock runs out, before the
   * autopick fires. `0` disables overtime: the deadline is then hard.
   */
  overtime_seconds: number;
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

export interface DraftExportResponse extends DraftSession {
  advisories: string[];
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

/** One public registration answer, ready to render on the player card.
 *  Every custom question the organizer left PUBLIC reaches the draft board, and
 *  the server sends the field's CURRENT label and schema kind with each value so
 *  the draft client needs no form schema of its own. */
interface DraftPlayerCustomField {
  key: string;
  label: string;
  type: FormField["kind"];
  value: unknown;
}

/** Where a role's resolved rank came from — mirrors `shared.domain.roster.RankSource`. */
type DraftRankSource = "author" | "registration" | "workspace" | "native" | "none";

export interface DraftPlayer {
  id: number;
  session_id: number;
  /** null for a mix seat */
  registration_id: number | null;
  user_id: number | null;
  /** The workspace member this seat is: set on every mix seat (the room ties it to its lineup seat), null otherwise. */
  workspace_member_id?: number | null;
  identity: PlayerIdentity | null;
  /** The player's canonical unique name: every `/users/<name>` link is built from it, never from a game handle. */
  player_name: string | null;
  /**
   * `null` when the player has no playable role left — an organizer can strip
   * every rank mid-draft. Render that as "no role", never as a default one.
   */
  primary_role: RoleRef | null;
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
  /**
   * A captain's seat role: the role the organizer pinned while it stays
   * playable, else their lead role. `null` for everyone else — their roster
   * role is the pick's `target_role`.
   */
  captain_role: RoleRef | null;
  secondary_roles: RoleRef[];
  role_ranks: Record<string, number>;
  /** Per-role provenance of `role_ranks`, keyed the same way. */
  role_sources: Record<string, DraftRankSource>;
  role_top_characters: Record<string, Array<{ entity_id: number | null; slug: string; image_path: string | null }>>;
  /** Sub-role per playable role (hitscan, main heal…), keyed like `role_ranks`; absent when none. */
  role_sub_roles: Record<string, string>;
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
  target_role: RoleRef | null;
  target_rank_value: number | null;
  status: DraftPickStatus;
  picked_player_id: number | null;
  picked_by_user_id: number | null;
  is_autopick: boolean;
  is_admin_override: boolean;
  clock_started_at: string | null;
  clock_expires_at: string | null;
  /**
   * Set the moment the main clock expired and the overtime phase began;
   * `clock_expires_at` then holds the OVERTIME deadline. Null while the pick
   * is on its main clock (or when the session runs without overtime).
   */
  overtime_started_at: string | null;
  version: number;
}

export interface DraftBoard {
  session: DraftSession;
  teams: DraftTeam[];
  picks: DraftPick[];
  players: DraftPlayer[]; // all pool players; derive availability + rosters client-side
  current_pick: DraftPick | null;
  last_event_id: number | null;
}

// A slot code is a role code of the owner game's rated dimension, or the open-slot sentinel (`flex`); the shape
// the session was created with is the closed set, and names come from the scoped ontology.
interface DraftSlot {
  team_id: number;
  slot_code: SlotCode;
  ordinal: number;
}

interface DraftSlotDeficit {
  slot_code: SlotCode;
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
  role: RoleRef;
  is_safe: boolean;
  reason_code: string | null;
  unmatched_slots: DraftSlot[];
  blocking_player_ids: number[];
}

export interface DraftPickOptionsResponse {
  pick_id: number;
  pick_version: number;
  draft_team_id: number;
  options: DraftPickOption[];
}

/** The server's fit of every seatable (player, role) for one team, normalized 1..99. */
export interface DraftTeamFitScore {
  player_id: number;
  /** `null` under an all-flex shape: nobody is seated on a role. */
  role: RoleRef | null;
  score: number;
}

export interface DraftTeamFitResponse {
  session_id: number;
  team_id: number;
  scores: DraftTeamFitScore[];
}

/** What the autopick would take for the team on the clock right now. */
export interface DraftAutopickPreview {
  player_id: number;
  role: RoleRef | null;
  /** `queue`: the first safe player of the captain's list; `fit`: the strategy's best fit. */
  source: "queue" | "fit";
}

/** A captain's private pick queue ("My list"): the autopick's priority order. */
export interface DraftTeamQueueResponse {
  team_id: number;
  /** Stored order, narrowed to players still available. */
  player_ids: number[];
  /** Non-null only while this team is on the clock. */
  autopick_preview: DraftAutopickPreview | null;
}

export type DraftJournalAction =
  | "pick_made"
  | "pick_autopicked"
  | "pick_overridden"
  | "pick_extended"
  | "paused"
  | "resumed"
  | "rollback"
  | "started"
  | "completed"
  | "cancelled"
  | "player_role_added";

export interface DraftJournalEntry {
  id: number;
  created_at: string;
  /** Open-ended on the wire; render unknown actions generically. */
  action: DraftJournalAction | (string & {});
  actor_auth_user_id: number | null;
  actor_name: string | null;
  reason: string | null;
  pick_no: number | null;
  team_id: number | null;
  player_id: number | null;
  role: RoleRef | null;
  seconds: number | null;
}

export interface DraftJournalResponse {
  session_id: number;
  entries: DraftJournalEntry[];
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
  /** On `draft.overtime_started`: when the main clock ran out. */
  overtime_started_at?: string | null;
  /** On `draft.clock_extended`: how many seconds the admin added. */
  added_seconds?: number;
  remaining_ms?: number;
  count_bucket?: string;
  /** Why the draft paused, on `draft.blocked`. */
  blocked_reason?: string;
  /** Why an autopick fired, on `draft.autopicked`. Informational. */
  autopick_reason?: string;
  target_role?: RoleRef | null;
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
  pick_time_seconds?: number;
  overtime_seconds?: number;
  autopick_strategy?: DraftAutopickStrategy;
  allow_admin_override?: boolean;
  settings?: Record<string, unknown>;
}

interface DraftPoolCaptainInput {
  registration_id: number;
  name?: string | null;
  /** The role the captain is seated on; omitted/null = their lead role. */
  role?: RoleRef | null;
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
  role: RoleRef;
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
  role: RoleRef;
  player_version: number;
  committed: boolean;
  before: DraftFeasibility;
  after: DraftFeasibility;
}

/** Admin: add seconds to the current pick's clock (works while paused too). */
export interface DraftPickExtendRequest {
  expected_version: number;
  seconds: number;
}
