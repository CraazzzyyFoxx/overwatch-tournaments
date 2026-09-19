export interface PlayerData {
  uuid: string;
  name: string;
  assigned_rating: number;
  role_discomfort: number;
  is_captain: boolean;
  is_flex?: boolean;
  role_preferences: string[];
  all_ratings: Record<string, number>;
  /** Per-role discomfort snapshot from the solver; keyed like `all_ratings`. */
  all_discomforts?: Record<string, number>;
  sub_role?: string | null;
}

interface TeamData {
  id: number;
  name: string;
  average_mmr: number;
  rating_variance: number;
  total_discomfort: number;
  max_discomfort: number;
  roster: Record<string, PlayerData[]>;
}

interface RoleFeasibility {
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

/** A balancer config: knob values keyed by knob name.
 *
 * Deliberately not a closed list of fields. Knobs are declared in exactly one
 * place -- `AlgorithmConfig` on the backend -- and reach the client as
 * `BalancerConfigResponse.fields`, which is what the drawer renders. A second
 * hand-maintained copy here only ever drifted: it still listed two weights the
 * cost function stopped reading (`intra_team_variance_weight`,
 * `role_spread_weight`) and was missing `team_max_pain_weight` and
 * `time_limit_ms`, so the drawer offered those two and the client stripped them
 * back out before the request. */
export type BalancerConfig = Record<string, BalancerConfigValue>;

/** A knob value on the wire, or the raw string a number input holds mid-edit;
 * `sanitizeBalancerConfig` coerces that back to a number. */
export type BalancerConfigValue =
  | number
  | boolean
  | string
  | Record<string, number>
  | null
  | undefined;

/** Widget the drawer renders for a knob; mirrors the backend's `ConfigControl`. */
type BalancerConfigFieldType = "boolean" | "float" | "integer" | "slider";

export interface BalancerConfigField {
  key: string;
  label: string;
  description: string;
  type: BalancerConfigFieldType;
  group: "Algorithm" | "Quality weights" | "Strategy" | "Solver output";
  default: BalancerConfigValue;
  limits?: { min: number; max: number } | null;
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

type BalanceJobStatus = "queued" | "running" | "succeeded" | "failed";

interface BalanceJobProgress {
  current?: number;
  total?: number;
  percent?: number;
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
