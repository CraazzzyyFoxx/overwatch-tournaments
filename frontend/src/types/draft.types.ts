// Live Draft types — mirror the balancer-service DTOs (src/schemas/draft.py).

export type DraftStatus = "setup" | "ready" | "live" | "paused" | "completed" | "cancelled";

export type DraftFormat = "snake" | "linear" | "custom";
export type DraftPoolSource = "balancer_balance" | "manual";
export type DraftAutopickStrategy = "best_fit" | "best_available" | "role_need";
export type DraftRole = "tank" | "dps" | "support";
export type DraftPlayerStatus = "available" | "picked" | "removed";
export type DraftPickStatus = "upcoming" | "on_clock" | "completed" | "skipped" | "autopicked";

export interface DraftSession {
  id: number;
  tournament_id: number;
  workspace_id: number;
  status: DraftStatus;
  format: DraftFormat;
  rounds: number;
  pick_time_seconds: number;
  team_size: number;
  current_pick_id: number | null;
  pool_source: DraftPoolSource;
  source_balance_id: number | null;
  autopick_strategy: DraftAutopickStrategy;
  allow_admin_override: boolean;
  exported_at: string | null;
  export_status: string | null;
  settings_json: Record<string, any>;
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

export interface DraftPlayer {
  id: number;
  session_id: number;
  user_id: number | null;
  battle_tag: string | null;
  primary_role: DraftRole;
  sub_role: string | null;
  is_flex: boolean;
  division_number: number | null;
  rank_value: number | null;
  status: DraftPlayerStatus;
  is_captain: boolean;
  drafted_by_team_id: number | null;
  secondary_roles_json: string[] | null;
  role_ranks: Record<string, number>;
  role_top_heroes: Record<string, Array<string | { slug: string; image_path: string | null }>>;
  additional_info: Record<string, unknown>;
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

export interface DraftSuggestion {
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

// Realtime event payloads (topic tournament:{id}:draft).
export type DraftEventType =
  | "draft.session_updated"
  | "draft.pick_started"
  | "draft.pick_made"
  | "draft.autopicked"
  | "draft.paused"
  | "draft.resumed"
  | "draft.completed"
  | "draft.cancelled"
  | "draft.presence"
  | "draft.rollback";

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
  reason?: string;
  [key: string]: unknown;
}

// Request bodies.
export interface DraftSessionCreateRequest {
  pool_source?: DraftPoolSource;
  source_balance_id?: number | null;
  format?: DraftFormat;
  rounds?: number;
  pick_time_seconds?: number;
  team_size?: number;
  autopick_strategy?: DraftAutopickStrategy;
  allow_admin_override?: boolean;
  settings?: Record<string, unknown>;
}

export interface DraftSeedCaptainInput {
  user_id?: number | null;
  battle_tag?: string | null;
  name: string;
  draft_position: number;
}

export interface DraftSeedPlayerInput {
  user_id?: number | null;
  battle_tag?: string | null;
  primary_role: DraftRole;
  secondary_roles?: DraftRole[];
  sub_role?: string | null;
  is_flex?: boolean;
  division_number?: number | null;
  rank_value?: number | null;
}

export interface DraftPoolCaptainInput {
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
  // Manual fallback.
  captains?: DraftSeedCaptainInput[];
  players?: DraftSeedPlayerInput[];
}
