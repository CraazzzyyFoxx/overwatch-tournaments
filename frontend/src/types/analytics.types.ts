import { Player, Team } from "@/types/team.types";

// ────────────────────────────────────────────────────────────────────────────
// v1 — existing types kept exactly for backwards compatibility.
// ────────────────────────────────────────────────────────────────────────────

export interface AlgorithmAnalytics {
  id: number;
  name: string;
  /**
   * Whether this algorithm has computed shift rows for the queried tournament.
   * Populated only when algorithms are fetched with a tournament context; used
   * to prefer a richer algorithm (e.g. "OpenSkill + ML") as the default when it
   * actually has data, and fall back otherwise.
   */
  has_data?: boolean | null;
}

export interface PlayerAnalytics extends Player {
  move_1: number;
  move_2: number;
  points: number;
  shift: number;
  confidence: number;
  effective_evidence: number;
  sample_tournaments: number;
  sample_matches: number;
  log_coverage: number;
  predicted_division: number | null;
  predicted_direction: "promote" | "demote" | "flat";
  predicted_delta: number;
  anomalies: AnalyticsAnomaly[];
}

export interface TeamAnalytics extends Team {
  players: PlayerAnalytics[];
  wins: number;
  losses: number;
  predicted_place: number | null;
  placement_delta: number | null;
  avg_confidence: number;
  manual_shift_points: number;
  anomalies: AnalyticsAnomaly[];
  balancer_shift: number;
  manual_shift: number;
  total_shift: number;
}

export interface AnalyticsAnomaly {
  player_id: number;
  kind: AnomalyKind | string;
  score: number;
  confidence?: number;
  reasons: string[];
  encounter_id?: number | null;
}

export interface TournamentAnalyticsSummary {
  total_teams: number;
  total_players: number;
  avg_confidence: number;
  anomaly_count: number;
  manual_shift_team_count: number;
  newcomer_count: number;
  divergent_team_count: number;
  avg_placement_delta: number;
}

export interface TournamentAnalytics {
  teams: TeamAnalytics[];
  teams_wins: Record<number, number>;
  summary: TournamentAnalyticsSummary;
}

export interface AnalyticsRecalculateResponse {
  message: string;
  algorithms: string[];
}

// ────────────────────────────────────────────────────────────────────────────
// v2 ML — new analytics-service endpoints (Performance / Shift / Standings /
// Match Quality / Explainability).
// ────────────────────────────────────────────────────────────────────────────

export interface PerformanceV2 {
  id: number;
  tournament_id: number;
  player_id: number;
  algorithm_id: number;
  impact_score: number; // 0-100 percentile within (tournament, role)
  raw_value: number; // predicted residual contribution (-1..1)
  confidence: number; // 0-1
  log_coverage: number; // 0-1
  local_mean: number;
  local_std: number;
  local_residual: number;
  local_zscore: number;
  local_percentile: number; // 0-100 within nearby divisions
  local_reference_n: number;
  local_band_min_div: number | null;
  local_band_max_div: number | null;
  top_features: TopFeatureContribution[] | null;
}

export interface TopFeatureContribution {
  feature: string;
  shap: number;
  value: number | null;
}

export interface StandingsDistribution {
  id: number;
  tournament_id: number;
  team_id: number;
  algorithm_id: number;
  mean_position: number;
  median_position: number;
  p10_position: number;
  p90_position: number;
  prob_top1: number;
  prob_top3: number;
  prob_top8: number;
  position_histogram: Record<string, number>; // {"1": count, "2": count, ...}
}

export type AnomalyKind = "smurf" | "troll" | "throw" | "sandbag";

export interface AnomalyFlag {
  player_id: number;
  kind: AnomalyKind;
  score: number;
  reasons: string[];
  encounter_id?: number;
}

export interface MatchQuality {
  id: number;
  encounter_id: number;
  algorithm_id: number;
  competitiveness: number; // 0-100
  predictability: number; // 0-100
  skill_balance: number; // 0-100
  quality_score: number; // 0-100 weighted aggregate
  anomaly_flags: AnomalyFlag[] | null;
}

export interface PlayerAnomaly {
  tournament_id: number;
  player_id: number;
  kind: AnomalyKind | string;
  score: number;
  confidence: number;
  reasons: string[];
  evidence: Record<string, unknown> | null;
  source_encounter_id: number | null;
}

export type AnomalyVerdict = "confirmed" | "dismissed";

export interface AnomalyFeedback {
  id: number;
  tournament_id: number;
  player_id: number;
  kind: string;
  verdict: AnomalyVerdict;
  reviewer_user_id: number | null;
  note: string | null;
}

export interface AnomalyFeedbackInput {
  tournament_id: number;
  player_id: number;
  kind: string;
  verdict: AnomalyVerdict;
  note?: string;
}

export interface ExplanationContribution {
  feature: string;
  shap: number;
  value: number | null;
}

export interface Explanation {
  algorithm_id: number;
  entity_id: number;
  entity_kind: "player" | "team" | "encounter";
  tournament_id: number;
  base_value: number;
  contributions: ExplanationContribution[];
}

export type MLModelKind = "performance" | "shift" | "standings" | "match_quality";

export interface MLArtifact {
  id: number;
  algorithm_id: number;
  model_kind: MLModelKind | string;
  role: string | null;
  version: string;
  storage_uri: string;
  feature_version: string;
  training_cutoff_tournament_id: number | null;
  metrics: Record<string, unknown> | null;
  feature_importance: Record<string, unknown> | null;
  is_active: boolean;
  created_at: string;
  updated_at: string | null;
}

export interface JobAcceptedResponse {
  message: string;
  job: "train" | "infer";
  correlation_id: string;
}

// ────────────────────────────────────────────────────────────────────────────
// Unified analytics job — single pipeline replacing Recalculate/Train/Infer.
// ────────────────────────────────────────────────────────────────────────────

export type AnalyticsJobKind = "compute" | "train_ml";
export type AnalyticsJobStatus = "pending" | "running" | "succeeded" | "failed";

export interface AnalyticsJobProgressStage {
  state: "running" | "done" | "failed";
  detail?: Record<string, unknown>;
}

export interface AnalyticsJob {
  id: number;
  workspace_id: number | null;
  tournament_id: number;
  requested_by_user_id: number | null;
  kind: AnalyticsJobKind;
  status: AnalyticsJobStatus;
  algorithms: string[] | null;
  training_workspace_ids: number[] | null;
  progress: Record<string, AnalyticsJobProgressStage>;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface AnalyticsJobCreate {
  tournament_id: number;
  kind: AnalyticsJobKind;
  algorithms?: string[];
  training_workspace_ids?: number[] | null;
}

/** Payload of `analytics_job.<status>` events emitted via realtime WS. */
export interface AnalyticsJobRealtimePayload {
  job_id: number;
  workspace_id: number;
  tournament_id: number;
  kind: AnalyticsJobKind;
  status: AnalyticsJobStatus;
  progress: Record<string, AnalyticsJobProgressStage>;
  error: string | null;
}
