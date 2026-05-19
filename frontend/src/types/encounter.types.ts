import { MapRead } from "@/types/map.types";
import { Team, TeamWithStats } from "@/types/team.types";
import {
  EncounterResultStatus,
  Stage,
  StageItem,
  Tournament,
  TournamentGroup,
} from "@/types/tournament.types";

export interface Score {
  home: number;
  away: number;
}

export interface Encounter {
  id: number;
  created_at: Date;
  updated_at: Date | null;
  name: string;
  home_team_id: number;
  away_team_id: number;
  score: Score;
  round: number;
  best_of: number;
  tournament_id: number;
  tournament_group_id?: number | null;
  stage_id: number | null;
  stage_item_id: number | null;
  challonge_id: number | null;
  challonge_slug?: string | null;
  status: string;
  closeness: number | null;
  has_logs: boolean;
  result_status: EncounterResultStatus;
  scheduled_at: Date | string | null;
  started_at: Date | string | null;
  ended_at: Date | string | null;
  current_map_index: number | null;
  submitted_by_id: number | null;
  submitted_at: Date | string | null;
  confirmed_by_id: number | null;
  confirmed_at: Date | string | null;

  matches: Match[];
  home_team: Team;
  away_team: Team;
  tournament: Tournament;
  stage?: Stage | null;
  stage_item?: StageItem | null;
  tournament_group?: TournamentGroup | null;
}

export interface Match {
  id: number;
  created_at: Date;
  updated_at: Date | null;
  home_team_id: number;
  away_team_id: number;
  score: Score;
  time: number;
  encounter_id: number;
  map_id: number;
  log_name: string;
  code: string | null;

  map: MapRead | null;
  home_team: Team | null;
  away_team: Team | null;
  encounter: Encounter | null;
}

export interface MatchWithStats extends Match {
  rounds: number;
  home_team: TeamWithStats;
  away_team: TeamWithStats;
}

export type EncounterScope = "all" | "my_team";

export interface EncounterFilters {
  tournament_id?: number | null;
  stage_id?: number | null;
  stage_item_id?: number | null;
  best_of?: number | null;
  status?: string | null;
  has_logs?: boolean | null;
  closeness_min?: number | null;
  closeness_max?: number | null;
  scope?: EncounterScope;
  sort?: string | null;
}

export interface EncounterSavedView {
  id: number;
  workspace_id: number;
  name: string;
  filters: EncounterFilters & { query?: string };
  sort_order: number;
}

export interface EncounterKpis {
  total_encounters: number;
  recent_count: number;
  with_logs_count: number;
  with_logs_pct: number;
  avg_closeness: number | null;
  live_now_count: number;
  upcoming_count: number;
}

export interface EncounterHistogramBucket {
  label: string;
  start: number;
  end: number;
  count: number;
}

export interface EncounterScoreHeatmapCell {
  home: number;
  away: number;
  count: number;
}

export interface EncounterStageSplit {
  name: string;
  count: number;
  pct: number;
}

export interface EncounterMapMetric {
  name: string;
  count: number;
}

export interface EncounterPulse {
  avg_series_seconds: number | null;
  completed_series_count: number;
  sweep_rate: number;
  sweep_count: number;
  went_distance_count: number;
  reverse_sweep_rate: number;
  most_decisive_map: string | null;
}

export interface EncounterSideBalance {
  home_wins: number;
  away_wins: number;
  home_win_pct: number;
  away_win_pct: number;
}

export interface EncounterFeatured {
  closest: Encounter[];
  upcoming: Encounter[];
  live: Encounter[];
}

export interface EncounterOverview {
  kpis: EncounterKpis;
  preset_counts: Record<string, number>;
  closeness_histogram: EncounterHistogramBucket[];
  score_heatmap: EncounterScoreHeatmapCell[];
  stage_split: EncounterStageSplit[];
  featured: EncounterFeatured;
  hot_maps: EncounterMapMetric[];
  pulse: EncounterPulse;
  side_balance: EncounterSideBalance;
}
