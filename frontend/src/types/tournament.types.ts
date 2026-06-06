import { User } from "@/types/user.types";
import { Team } from "@/types/team.types";
import { Encounter } from "@/types/encounter.types";
import { DivisionGridVersion } from "@/types/workspace.types";

// ─── Enums ──────────────────────────────────────────────────────────────────

export type TournamentStatus =
  | "registration"
  | "draft"
  | "check_in"
  | "live"
  | "playoffs"
  | "completed"
  | "archived";

export type StageType =
  | "round_robin"
  | "single_elimination"
  | "double_elimination"
  | "swiss";

export type StageItemType =
  | "group"
  | "bracket_upper"
  | "bracket_lower"
  | "single_bracket";

export type StageItemInputType = "final" | "tentative" | "empty";

export type EncounterResultStatus =
  | "none"
  | "pending_confirmation"
  | "confirmed"
  | "disputed";

export type MapPoolEntryStatus = "available" | "picked" | "banned" | "played";
export type MapPickSide = "home" | "away" | "decider" | "admin";
export type MapVetoAction = "pick" | "ban";

// ─── Legacy (kept for backward compat) ──────────────────────────────────────

export interface TournamentGroup {
  id: number;
  created_at: Date;
  updated_at: Date | null;
  name: string;
  description: string | null;
  is_groups: boolean;
  challonge_id: number | null;
  challonge_slug: string | null;
  stage_id: number | null;
}

// ─── Stage Model ────────────────────────────────────────────────────────────

export interface StageItemInput {
  id: number;
  stage_item_id: number;
  slot: number;
  input_type: StageItemInputType;
  team_id: number | null;
  source_stage_item_id: number | null;
  source_position: number | null;
}

export interface StageItem {
  id: number;
  stage_id: number;
  name: string;
  type: StageItemType;
  order: number;
  inputs: StageItemInput[];
}

export interface Stage {
  id: number;
  tournament_id: number;
  name: string;
  description: string | null;
  stage_type: StageType;
  max_rounds: number;
  advance_count: number | null;
  order: number;
  is_active: boolean;
  is_completed: boolean;
  settings_json: Record<string, unknown> | null;
  challonge_id: number | null;
  challonge_slug: string | null;
  items: StageItem[];
}

// ─── Tournament ─────────────────────────────────────────────────────────────

export interface Tournament {
  id: number;
  created_at: Date;
  updated_at: Date | null;
  workspace_id: number;
  name: string;
  start_date: Date;
  end_date: Date;
  number: number;
  description: string | null;
  challonge_id: number | null;
  challonge_slug: string | null;
  is_league: boolean;
  is_finished: boolean;
  team_formation: string;
  status: TournamentStatus;
  registration_opens_at: Date | null;
  registration_closes_at: Date | null;
  check_in_opens_at: Date | null;
  check_in_closes_at: Date | null;
  win_points: number;
  draw_points: number;
  loss_points: number;

  stages: Stage[];
  groups?: TournamentGroup[];
  participants_count: number | null;
  registrations_count: number | null;
  division_grid_version_id: number | null;
  division_grid_version: DivisionGridVersion | null;
}

// ─── Map Pool ───────────────────────────────────────────────────────────────

export interface EncounterMapPoolEntry {
  id: number;
  map_id: number;
  order: number;
  picked_by: MapPickSide | null;
  status: MapPoolEntryStatus;
}

export interface EncounterMapPoolState {
  pool: EncounterMapPoolEntry[];
  viewer_side: "home" | "away" | null;
  viewer_can_act: boolean;
  allowed_actions: MapVetoAction[];
  current_step_index: number | null;
  current_step: string | null;
  expected_action: MapVetoAction | "decider" | null;
  turn_side: "home" | "away" | null;
  is_complete: boolean;
}

export interface MapVetoConfig {
  id: number;
  tournament_id: number;
  stage_id: number | null;
  veto_sequence_json: string[];
  map_pool_ids: number[];
}

export interface OwalStandingDay {
  tournament: Tournament;
  team: string;
  role: string;
  points: number;
  wins: number;
  draws: number;
  losses: number;
  win_rate: number;
}

export interface OwalStanding {
  user: User;
  role: string;
  division: number;
  days: Record<string, OwalStandingDay>;
  count_days: number;
  place: number;
  best_3_days: number;
  avg_points: number;
  wins: number;
  draws: number;
  losses: number;
  win_rate: number;
}

export interface OwalStandings {
  days: Tournament[];
  standings: OwalStanding[];
}

export interface Standings {
  id: number;
  tournament_id: number;
  team_id: number;
  stage_id: number | null;
  stage_item_id: number | null;
  position: number;
  overall_position: number;
  matches: number;
  win: number;
  draw: number;
  lose: number;
  points: number;
  buchholz: number | null;
  tb: number | null;
  score_differential: number | null;
  ranking_context: Record<string, string | number | null> | null;
  tb_metrics: Record<string, number | null> | null;
  source_rule_profile: string | null;
  tiebreak_order: string[] | null;

  team: Team | null;
  tournament: Tournament | null;
  stage: Stage | null;
  stage_item: StageItem | null;
  group?: TournamentGroup | null;
  group_id?: number;
  matches_history: Encounter[];
}

export interface OwalStack {
  user_1: User;
  user_2: User;
  games: number;
  avg_position: number;
}
