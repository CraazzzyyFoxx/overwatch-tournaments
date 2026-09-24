import { MapRead } from "@/types/map.types";
import { Team, TeamWithStats } from "@/types/team.types";
import {
  EncounterGame,
  EncounterResultStatus,
  Stage,
  StageItem,
  Tournament,
} from "@/types/tournament.types";

export interface Score {
  home: number;
  away: number;
}

/**
 * One incoming advancement edge: `role` of `encounter_id` fills `slot` of this
 * encounter. The bracket's real topology, so a reader can label an unresolved
 * slot without inferring the bracket's shape. Absent on a bracket generated
 * before advancement edges were recorded.
 */
export interface EncounterSlotSource {
  encounter_id: number;
  role: "winner" | "loser";
  slot: "home" | "away";
}

/**
 * A game as the public encounter read serves it: the position also names its
 * map, so a map can be pictured before (or without) a parsed log. The pick-ban
 * room's `PickBanGame` carries no map object — only `map_id`.
 */
export interface EncounterGameWithMap extends EncounterGame {
  map: Match["map"];
}

/**
 * Which shape of result the encounter carries: a duel is the two-team series
 * every list below assumes, an `ffa` encounter is a multi-team lobby whose
 * rows live in `FfaLobby` (`@/types/ffa.types`) and whose `score`, `home_team`
 * and `away_team` are placeholders. List reads are duel-only by default.
 */
export type EncounterFormat = "duel" | "ffa";

export interface Encounter {
  id: number;
  created_at: Date;
  updated_at: Date | null;
  name: string;
  format: EncounterFormat;
  home_team_id: number;
  away_team_id: number;
  score: Score;
  round: number;
  best_of: number;
  tournament_id: number;
  stage_id: number | null;
  stage_item_id: number | null;
  challonge_id: number | null;
  status: string;
  closeness: number | null;
  has_logs: boolean;
  result_status: EncounterResultStatus;
  scheduled_at: Date | string | null;
  started_at: Date | string | null;
  ended_at: Date | string | null;
  current_map_index: number | null;
  // Who decided the result — and every earlier decision — lives in the result
  // audit, not in a single slot that only ever remembered the last writer.
  confirmed_at: Date | string | null;
  /** Empty on a bracket whose advancement edges were never recorded. */
  sources?: EncounterSlotSource[];

  matches: Match[];
  /**
   * One entry per position of the series, in play order — the encounter's own
   * result authority. A `Match` row is a parsed log, a separate contract: the
   * two are rendered as two facts, never merged (spec §11).
   */
  games: EncounterGameWithMap[];
  home_team: Team;
  away_team: Team;
  tournament: Tournament;
  stage?: Stage | null;
  stage_item?: StageItem | null;
}

interface CaptainMapCode {
  id: number;
  map_index: number;
  map_id: number | null;
  code: string;
}

export interface CaptainReport {
  id: number;
  encounter_id: number;
  team_id: number;
  side: "home" | "away" | null;
  reporter_user_id: number | null;
  /** Display name of the captain who filed it (`CaptainReportRead.reporter_name`). */
  reporter_name?: string | null;
  home_score: number;
  away_score: number;
  /** 1..10, or null when the tournament disables/does not require match quality. */
  closeness: number | null;
  map_codes: CaptainMapCode[];
  comment: string | null;
  /** Organizer-defined text answers, keyed by `ReportCustomFieldDefinition.key`. */
  custom_fields: Record<string, string>;
  created_at: string | null;
  updated_at: string | null;
}

export interface ReportBuiltInFieldConfig {
  enabled: boolean;
  required: boolean;
}

export interface ReportCustomFieldDefinition {
  /** `^[a-z][a-z0-9_]{0,31}$`; the key under `CaptainReport.custom_fields`. */
  key: string;
  label: string;
  type: "text";
  required: boolean;
  placeholder: string | null;
}

/** Per-tournament configuration of the captain match-report form. */
export interface MatchReportForm {
  tournament_id: number;
  built_in_fields: {
    closeness: ReportBuiltInFieldConfig;
    map_codes: ReportBuiltInFieldConfig;
    comment: ReportBuiltInFieldConfig;
  };
  custom_fields: ReportCustomFieldDefinition[];
}

export interface CaptainReportsResponse {
  reports: CaptainReport[];
  form: MatchReportForm;
}

/**
 * Mirrors the backend `DEFAULT_BUILT_IN_FIELDS`. Used while the reports query is
 * in flight so the dialog renders its usual shape instead of flashing empty and
 * then growing fields under the captain's cursor.
 */
export const DEFAULT_MATCH_REPORT_BUILT_INS: MatchReportForm["built_in_fields"] = Object.freeze({
  closeness: Object.freeze({ enabled: true, required: true }),
  map_codes: Object.freeze({ enabled: true, required: false }),
  comment: Object.freeze({ enabled: true, required: false })
});

export interface Match {
  id: number;
  created_at: Date;
  updated_at: Date | null;
  home_team_id: number;
  away_team_id: number;
  score: Score;
  time: number | null;
  encounter_id: number;
  map_id: number;
  /**
   * Which map OF THE SERIES this row is, 1-based in play order. Null when
   * unknown — every parsed log, and every row written before the column
   * existed. It, not `map_id`, is what identifies a played map: a series may
   * play the same map twice (see `seriesMatchesByPosition`).
   */
  map_index: number | null;
  log_name: string | null;
  source: "log_parser" | "captain_report";
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

type EncounterScope = "all" | "my_team";

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

interface EncounterKpis {
  total_encounters: number;
  recent_count: number;
  with_logs_count: number;
  with_logs_pct: number;
  avg_closeness: number | null;
  live_now_count: number;
  upcoming_count: number;
}

interface EncounterHistogramBucket {
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

interface EncounterMapMetric {
  name: string;
  count: number;
}

interface EncounterPulse {
  avg_series_seconds: number | null;
  completed_series_count: number;
  sweep_rate: number;
  sweep_count: number;
  went_distance_count: number;
  reverse_sweep_rate: number;
  most_decisive_map: string | null;
}

interface EncounterSideBalance {
  home_wins: number;
  away_wins: number;
  home_win_pct: number;
  away_win_pct: number;
}

interface EncounterFeatured {
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
