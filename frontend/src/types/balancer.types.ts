export const SUPPORTED_BALANCER_ALGORITHMS = ["moo", "cpsat"] as const;

export type BalancerAlgorithm = (typeof SUPPORTED_BALANCER_ALGORITHMS)[number];

export const SUPPORTED_BALANCER_CONFIG_KEYS = [
  "role_mask",
  "algorithm",
  "population_size",
  "generation_count",
  "mutation_rate",
  "mutation_strength",
  "average_mmr_balance_weight",
  "role_discomfort_weight",
  "intra_team_variance_weight",
  "max_role_discomfort_weight",
  "team_total_balance_weight",
  "max_team_gap_weight",
  "role_line_balance_weight",
  "role_spread_weight",
  "intra_team_std_weight",
  "internal_role_spread_weight",
  "sub_role_collision_weight",
  "tank_impact_weight",
  "dps_impact_weight",
  "support_impact_weight",
  "tank_gap_weight",
  "tank_std_weight",
  "effective_total_std_weight",
  "use_captains",
  "convergence_patience",
  "convergence_epsilon",
  "mutation_rate_min",
  "mutation_rate_max",
  "island_count",
  "polish_max_passes",
  "greedy_seed_count",
  "stagnation_kick_patience",
  "crossover_rate",
  "max_result_variants"
] as const;

export type BalancerConfigKey = (typeof SUPPORTED_BALANCER_CONFIG_KEYS)[number];

export interface PlayerData {
  uuid: string;
  name: string;
  assigned_rating: number;
  role_discomfort: number;
  is_captain: boolean;
  is_flex?: boolean;
  role_preferences: string[];
  all_ratings: Record<string, number>;
  sub_role?: string | null;
}

export interface TeamData {
  id: number;
  name: string;
  average_mmr: number;
  rating_variance: number;
  total_discomfort: number;
  max_discomfort: number;
  roster: Record<string, PlayerData[]>;
}

export interface RoleFeasibility {
  role: string;
  supply: number;
  demand: number;
  flex_supply: number;
}

export interface FeasibilityReport {
  total_slots: number;
  structural_min_off_role: number;
  flex_player_count: number;
  roles: RoleFeasibility[];
}

export interface Statistics {
  average_mmr: number;
  mmr_std_dev: number;
  total_teams: number;
  players_per_team: number;
  off_role_count: number;
  sub_role_collision_count: number;
  unbalanced_count: number;
  average_total_rating?: number | null;
  total_rating_std_dev?: number | null;
  max_total_rating_gap?: number | null;
  balance_objective?: number | null;
  comfort_objective?: number | null;
  balance_objective_norm?: number | null;
  comfort_objective_norm?: number | null;
  composite_score?: number | null;
  off_role_rate?: number | null;
  off_role_above_minimum?: number | null;
  feasibility?: FeasibilityReport | null;
}

export interface BalanceResponse {
  teams: TeamData[];
  statistics: Statistics;
  benched_players?: PlayerData[];
  applied_config?: BalancerConfig | null;
}

export interface BalancerConfig {
  role_mask?: Record<string, number>;
  algorithm?: BalancerAlgorithm;
  population_size?: number;
  generation_count?: number;
  mutation_rate?: number;
  mutation_strength?: number;
  average_mmr_balance_weight?: number;
  role_discomfort_weight?: number;
  intra_team_variance_weight?: number;
  max_role_discomfort_weight?: number;
  team_total_balance_weight?: number;
  max_team_gap_weight?: number;
  role_line_balance_weight?: number;
  role_spread_weight?: number;
  intra_team_std_weight?: number;
  internal_role_spread_weight?: number;
  sub_role_collision_weight?: number;
  tank_impact_weight?: number;
  dps_impact_weight?: number;
  support_impact_weight?: number;
  tank_gap_weight?: number;
  tank_std_weight?: number;
  effective_total_std_weight?: number;
  use_captains?: boolean;
  convergence_patience?: number;
  convergence_epsilon?: number;
  mutation_rate_min?: number;
  mutation_rate_max?: number;
  island_count?: number;
  polish_max_passes?: number;
  greedy_seed_count?: number;
  stagnation_kick_patience?: number;
  crossover_rate?: number;
  max_result_variants?: number;
}

export type BalancerConfigFieldType = "boolean" | "float" | "integer" | "role_mask" | "select";

export interface BalancerConfigField {
  key: BalancerConfigKey;
  label: string;
  description: string;
  type: BalancerConfigFieldType;
  group: "Roles" | "Algorithm" | "Quality weights" | "Strategy" | "Solver output";
  default: unknown;
  limits?: { min: number; max: number } | null;
  options?: string[];
}

export interface BalanceJobResult {
  variants: BalanceResponse[];
}

export interface BalancerConfigResponse {
  defaults: BalancerConfig;
  limits: Record<string, { min: number; max: number }>;
  presets: Record<string, BalancerConfig>;
  fields: BalancerConfigField[];
}

export type BalanceJobStatus = "queued" | "running" | "succeeded" | "failed";

export interface BalanceJobProgress {
  current?: number;
  total?: number;
  percent?: number;
}

export interface BalanceJobEvent {
  event_id: number;
  timestamp: number;
  level: string;
  status: BalanceJobStatus;
  stage: string;
  message: string;
  progress?: BalanceJobProgress | null;
}

export interface BalanceJobCreateResponse {
  job_id: string;
  status: BalanceJobStatus;
  status_url: string;
  result_url: string;
  stream_url: string;
}

export interface BalanceJobStatusResponse {
  job_id: string;
  status: BalanceJobStatus;
  stage?: string | null;
  created_at: number;
  started_at?: number | null;
  finished_at?: number | null;
  progress?: BalanceJobProgress | null;
  error?: string | null;
  events_count: number;
}
