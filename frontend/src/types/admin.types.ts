// Admin CRUD Types

// ─── Global Settings (parser.*) ───────────────────────────────────────────────

export interface SettingRead {
  key: string;
  value: Record<string, unknown>;
  description: string | null;
  updated_at: string | null;
  updated_by: number | null;
}

export interface SettingUpsertInput {
  value: Record<string, unknown>;
  description?: string | null;
}

export type RankCollectionScope = "registrations_only" | "all";

export interface RankCollectionConfig {
  enabled: boolean;
  interval_seconds: number;
  batch_size: number;
  rate_limit_per_minute: number;
  scope: RankCollectionScope;
  extra_accounts_per_registration: number;
  max_consecutive_failures: number;
  backoff_base_seconds: number;
}

export interface RankMappingEntry {
  division: string;
  tier: number;
  rank_value: number;
}

export interface RankMappingConfig {
  version: string;
  entries: RankMappingEntry[];
}

// ─── Rank collection status / manual trigger (parser admin) ────────────────────

export interface RankCollectionStatusRow {
  battle_tag_id: number;
  battle_tag: string;
  status: string | null;
  last_checked_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
  next_eligible_at: string | null;
  priority_tier: number;
}

export interface CollectTriggerInput {
  user_id?: number | null;
  battle_tag_ids?: number[] | null;
}

export interface CollectTriggerResult {
  enqueued: number;
}

export interface RankFetchLogRow {
  id: number;
  battle_tag_id: number | null;
  battle_tag: string;
  status: string;
  source: string;
  error: string | null;
  snapshots_written: number;
  created_at: string;
}

export interface RankFetchLogQuery {
  status?: string;
  source?: string;
  before_id?: number;
  limit?: number;
}

// ─── Tournament ──────────────────────────────────────────────────────────────

import type {
  StageItemType,
  StageType,
  StageItemInputType,
  TournamentStatus
} from "@/types/tournament.types";

export interface TournamentCreateInput {
  workspace_id: number;
  name: string;
  number?: number;
  description?: string;
  is_league: boolean;
  status?: TournamentStatus;
  start_date: string;
  end_date: string;
  registration_opens_at?: string | null;
  registration_closes_at?: string | null;
  check_in_opens_at?: string | null;
  check_in_closes_at?: string | null;
  win_points?: number;
  draw_points?: number;
  loss_points?: number;
  division_grid_version_id?: number | null;
}

export interface TournamentUpdateInput {
  number?: number | null;
  name?: string;
  description?: string | null;
  challonge_slug?: string | null;
  is_league?: boolean;
  is_finished?: boolean;
  team_formation?: string;
  start_date?: string;
  end_date?: string;
  registration_opens_at?: string | null;
  registration_closes_at?: string | null;
  check_in_opens_at?: string | null;
  check_in_closes_at?: string | null;
  win_points?: number;
  draw_points?: number;
  loss_points?: number;
  division_grid_version_id?: number | null;
}

export interface TournamentStatusTransitionInput {
  status: TournamentStatus;
  force?: boolean;
}

// ─── Stage Admin ────────────────────────────────────────────────────────────

export interface StageCreateInput {
  name: string;
  description?: string | null;
  stage_type: StageType;
  max_rounds?: number;
  advance_count?: number | null;
  split_lower_bracket?: boolean;
  order?: number;
  settings_json?: Record<string, unknown> | null;
}

export interface StageUpdateInput {
  name?: string;
  description?: string | null;
  stage_type?: StageType;
  max_rounds?: number;
  advance_count?: number | null;
  split_lower_bracket?: boolean;
  order?: number;
  settings_json?: Record<string, unknown> | null;
}

export interface StageItemCreateInput {
  name: string;
  type: StageItemType;
  order?: number;
}

export interface StageItemInputCreateInput {
  slot: number;
  input_type?: StageItemInputType;
  team_id?: number | null;
  source_stage_item_id?: number | null;
  source_position?: number | null;
}

export interface StageItemInputUpdateInput {
  input_type?: StageItemInputType;
  team_id?: number | null;
  source_stage_item_id?: number | null;
  source_position?: number | null;
}

export interface StageMergeGroupStagesInput {
  source_stage_ids: number[];
  target_name?: string | null;
}

// ─── Captain Submission ─────────────────────────────────────────────────────

export interface ResultSubmissionInput {
  home_score: number;
  away_score: number;
}

export interface DisputeInput {
  reason?: string | null;
}

export interface VetoActionInput {
  map_id: number;
  action: "ban" | "pick";
}

// ─── Team ────────────────────────────────────────────────────────────────────

export interface TeamCreateInput {
  name: string;
  tournament_id: number;
  captain_id?: number;
  avg_sr?: number;
  total_sr?: number;
}

export interface TeamUpdateInput {
  name?: string;
  captain_id?: number;
  avg_sr?: number;
  total_sr?: number;
}

export interface ChallongeTeamMapping {
  participant_id: number;
  group_id: number | null;
  team_id: number;
}

export interface ChallongeTeamSyncRequest {
  mappings: ChallongeTeamMapping[];
}

export interface ChallongeTeamPreviewTeam {
  id: number;
  name: string;
  balancer_name: string;
}

export interface ChallongeTeamPreviewParticipant {
  participant_id: number;
  challonge_id: number;
  group_id: number | null;
  group_name: string | null;
  challonge_tournament_id: number;
  name: string;
  active: boolean;
  suggested_team_id: number | null;
  mapped_team_id: number | null;
}

export interface ChallongeTeamSyncPreview {
  teams: ChallongeTeamPreviewTeam[];
  participants: ChallongeTeamPreviewParticipant[];
}

export interface ChallongeTeamSyncResult {
  success: boolean;
  count: number;
  created: number;
  updated: number;
  unchanged: number;
  skipped: number;
  errors?: string[];
}

// ─── Player ──────────────────────────────────────────────────────────────────

export interface PlayerCreateInput {
  name: string;
  user_id: number;
  team_id: number;
  tournament_id: number;
  role: string;
  rank?: number;
  div?: number;
  sub_role?: string | null;
  is_newcomer?: boolean;
  is_newcomer_role?: boolean;
  is_substitution?: boolean;
  related_player_id?: number | null;
}

export interface PlayerUpdateInput {
  name?: string;
  role?: string;
  rank?: number;
  div?: number;
  sub_role?: string | null;
  is_newcomer?: boolean;
  is_newcomer_role?: boolean;
  is_substitution?: boolean;
  related_player_id?: number | null;
}

export interface PlayerSubRole {
  id: number;
  workspace_id: number;
  role: string;
  slug: string;
  label: string;
  description: string | null;
  sort_order: number;
  is_active: boolean;
}

export interface PlayerSubRoleCreateInput {
  workspace_id: number;
  role: string;
  label: string;
  slug?: string | null;
  description?: string | null;
  sort_order?: number;
  is_active?: boolean;
}

export interface PlayerSubRoleUpdateInput {
  role?: string;
  label?: string;
  slug?: string | null;
  description?: string | null;
  sort_order?: number;
  is_active?: boolean;
}

// ─── Encounter ───────────────────────────────────────────────────────────────

export interface EncounterCreateInput {
  tournament_id: number;
  tournament_group_id?: number | null;
  stage_id: number | null;
  stage_item_id: number | null;
  home_team_id: number | null;
  away_team_id: number | null;
  round: number;
  home_score?: number;
  away_score?: number;
  status?: string;
  name?: string;
}

export interface EncounterUpdateInput {
  tournament_group_id?: number | null;
  stage_id?: number | null;
  stage_item_id?: number | null;
  home_team_id?: number | null;
  away_team_id?: number | null;
  home_score?: number;
  away_score?: number;
  status?: string;
  round?: number;
  name?: string;
  closeness?: number | null;
}

export interface MatchUpdateInput {
  home_team_id?: number;
  away_team_id?: number;
  home_score?: number;
  away_score?: number;
  map_id?: number;
  code?: string | null;
  time?: number;
  log_name?: string;
}

// ─── Standing ────────────────────────────────────────────────────────────────

export interface StandingUpdateInput {
  position?: number;
  points?: number;
  win?: number;
  draw?: number;
  lose?: number;
  buchholz?: number;
  tb?: number;
}

// ─── User ────────────────────────────────────────────────────────────────────

export interface UserCreateInput {
  name: string;
}

export interface UserUpdateInput {
  name?: string;
}

export type UserMergeFieldChoice = "source" | "target";

export interface UserMergePreviewRequest {
  source_user_id: number;
  target_user_id: number;
}

export interface UserMergeFieldPolicy {
  name: UserMergeFieldChoice;
  avatar_url: UserMergeFieldChoice;
}

export interface UserMergeIdentitySelection {
  discord_ids: number[];
  battle_tag_ids: number[];
  twitch_ids: number[];
}

export interface UserMergeExecuteRequest extends UserMergePreviewRequest {
  preview_fingerprint: string;
  field_policy: UserMergeFieldPolicy;
  identity_selection: UserMergeIdentitySelection;
}

export interface UserMergeIdentityOption {
  id: number;
  value: string;
  duplicate_on_target: boolean;
}

export interface UserMergeUserSummary {
  id: number;
  name: string;
  avatar_url: string | null;
  discord: UserMergeIdentityOption[];
  battle_tag: UserMergeIdentityOption[];
  twitch: UserMergeIdentityOption[];
  auth_links: number;
}

export interface UserMergeConflictSummary {
  has_auth_conflict: boolean;
  summary: string | null;
}

export interface UserMergeFieldOptions {
  name: Record<UserMergeFieldChoice, string | null>;
  avatar_url: Record<UserMergeFieldChoice, string | null>;
}

export interface UserMergePreviewResponse {
  source: UserMergeUserSummary;
  target: UserMergeUserSummary;
  conflicts: UserMergeConflictSummary;
  affected_counts: Record<string, number>;
  field_options: UserMergeFieldOptions;
  preview_fingerprint: string;
}

export interface UserMergeIdentityResult {
  moved: Record<string, number[]>;
  deduped: Record<string, number[]>;
}

export interface UserMergeExecuteResponse {
  deleted_source_user_id: number;
  surviving_target_user_id: number;
  affected_counts: Record<string, number>;
  identity_results: UserMergeIdentityResult;
  audit_id: number;
}

// Discord Identity
export interface DiscordIdentityCreateInput {
  name: string;
}

export interface DiscordIdentityUpdateInput {
  name: string;
}

// BattleTag Identity
export interface BattleTagIdentityCreateInput {
  battle_tag: string;
}

export interface BattleTagIdentityUpdateInput {
  battle_tag: string;
}

// Twitch Identity
export interface TwitchIdentityCreateInput {
  name: string;
}

export interface TwitchIdentityUpdateInput {
  name: string;
}

// Generic (for backward compatibility)
export interface IdentityCreateInput {
  name?: string;
  battle_tag?: string;
}

export interface IdentityUpdateInput {
  name?: string;
  battle_tag?: string;
}

// ─── Hero ────────────────────────────────────────────────────────────────────

export interface HeroCreateInput {
  name: string;
  role: string;
  color?: string;
  image_path?: string;
}

export interface HeroUpdateInput {
  name?: string;
  role?: string;
  color?: string;
  image_path?: string;
}

// ─── Gamemode ────────────────────────────────────────────────────────────────

export interface Gamemode {
  id: number;
  created_at: Date;
  updated_at?: Date | null;
  name: string;
}

export interface GamemodeCreateInput {
  name: string;
}

export interface GamemodeUpdateInput {
  name?: string;
}

// ─── Map ─────────────────────────────────────────────────────────────────────

export interface MapCreateInput {
  name: string;
  gamemode_id: number;
}

export interface MapUpdateInput {
  name?: string;
  gamemode_id?: number;
}

// ─── Achievement ─────────────────────────────────────────────────────────────

export interface AchievementCreateInput {
  name: string;
  slug: string;
  description_ru: string;
  description_en: string;
  image_url?: string | null;
  hero_id?: number | null;
}

export interface AchievementUpdateInput {
  name?: string;
  slug?: string;
  description_ru?: string;
  description_en?: string;
  image_url?: string | null;
  hero_id?: number | null;
}

export interface AchievementRegistryEntry {
  slug: string;
  category: string;
  tournament_required: boolean;
}

export interface CalculationLogEntry {
  type: "start" | "progress" | "info" | "complete" | "error";
  slug?: string;
  index?: number;
  total?: number;
  status?: "running" | "done" | "error";
  message?: string;
  slugs?: string[];
  executed?: string[];
}

// ─── Achievement Rule Engine ──────────────────────────────────────────────────

export type AchievementCategory = "overall" | "hero" | "division" | "team" | "standing" | "match";
export type AchievementScope = "global" | "tournament" | "match";
export type AchievementGrain = "user" | "user_tournament" | "user_match";

export interface AchievementRule {
  id: number;
  workspace_id: number;
  slug: string;
  name: string;
  description_ru: string;
  description_en: string;
  image_url: string | null;
  hero_id: number | null;
  category: AchievementCategory;
  scope: AchievementScope;
  grain: AchievementGrain;
  condition_tree: Record<string, unknown>;
  depends_on: string[];
  enabled: boolean;
  rule_version: number;
  min_tournament_id: number | null;
  created_at: string;
  updated_at: string | null;
}

export interface AchievementRuleCreateInput {
  slug: string;
  name: string;
  description_ru: string;
  description_en: string;
  image_url?: string | null;
  hero_id?: number | null;
  category: AchievementCategory;
  scope: AchievementScope;
  grain: AchievementGrain;
  condition_tree: Record<string, unknown>;
  depends_on?: string[];
  enabled?: boolean;
  min_tournament_id?: number | null;
}

export interface AchievementRuleUpdateInput {
  slug?: string;
  name?: string;
  description_ru?: string;
  description_en?: string;
  image_url?: string | null;
  hero_id?: number | null;
  category?: AchievementCategory;
  scope?: AchievementScope;
  grain?: AchievementGrain;
  condition_tree?: Record<string, unknown>;
  depends_on?: string[];
  enabled?: boolean;
  rule_version?: number;
  min_tournament_id?: number | null;
}

export interface AchievementRulePortable {
  slug: string;
  name: string;
  description_ru: string;
  description_en: string;
  image_url: string | null;
  hero_id: number | null;
  category: AchievementCategory;
  scope: AchievementScope;
  grain: AchievementGrain;
  condition_tree: Record<string, unknown>;
  depends_on: string[];
  enabled: boolean;
  rule_version: number;
  min_tournament_id: number | null;
}

export interface AchievementRuleExportWorkspace {
  id: number;
  slug: string;
  name: string;
}

export interface AchievementRuleExportEnvelope {
  schema_version: number;
  exported_at: string;
  source_workspace: AchievementRuleExportWorkspace | null;
  rules: AchievementRulePortable[];
}

export interface AchievementImportWarning {
  slug: string;
  message: string;
}

export interface AchievementRuleImportResult {
  created: number;
  updated: number;
  warnings: AchievementImportWarning[];
}

export interface AchievementLibraryWorkspace {
  id: number;
  slug: string;
  name: string;
  rules_count: number;
}

export interface AchievementLibraryRule {
  slug: string;
  name: string;
  category: AchievementCategory;
  enabled: boolean;
  image_url: string | null;
}

export interface EvaluationRunRead {
  id: string;
  workspace_id: number;
  trigger: string;
  tournament_id: number | null;
  rules_evaluated: number;
  results_created: number;
  results_removed: number;
  started_at: string;
  finished_at: string | null;
  status: "running" | "done" | "failed" | "cancelled";
  error_message: string | null;
}

export interface SeedResultRead {
  seeded: number;
  removed: number;
}

export interface HardResetResultRead {
  seeded: number;
  removed: number;
  cleared_results: number;
  run: EvaluationRunRead;
}

export interface ConditionTreeValidateResponse {
  valid: boolean;
  errors: string[];
  inferred_grain: string | null;
}

export interface AchievementOverrideCreateInput {
  achievement_rule_id: number;
  user_id: number;
  tournament_id?: number | null;
  match_id?: number | null;
  action: "grant" | "revoke";
  reason: string;
}

export interface AchievementOverrideRead {
  id: number;
  achievement_rule_id: number;
  user_id: number;
  tournament_id: number | null;
  match_id: number | null;
  action: "grant" | "revoke";
  reason: string;
  granted_by: number;
  created_at: string;
}

export interface ConditionTypeInfo {
  name: string;
  grain: string;
  description: string;
  required_params: string[];
  optional_params: string[];
}

// ─── Challonge Sync ─────────────────────────────────────────────────────────

export interface ChallongeSyncLogEntry {
  id: number;
  created_at: string;
  source_id: number | null;
  direction: "import" | "export";
  operation: string | null;
  entity_type: string;
  entity_id: number | null;
  challonge_id: number | null;
  status: "success" | "failed" | "conflict";
  conflict_type: string | null;
  before_json?: Record<string, unknown> | null;
  after_json?: Record<string, unknown> | null;
  error_message: string | null;
}

// ─── Discord Channel Sync ─────────────────────────────────────────────────────

export interface DiscordChannelRead {
  id: number;
  tournament_id: number;
  guild_id: string;
  channel_id: string;
  channel_name: string | null;
  is_active: boolean;
}

export interface DiscordChannelInput {
  guild_id: string;
  channel_id: string;
  channel_name?: string | null;
  is_active: boolean;
}

// ─── Log Processing ───────────────────────────────────────────────────────────

export type LogProcessingStatus = "pending" | "processing" | "done" | "failed";
export type LogProcessingSource = "upload" | "discord" | "manual";

export interface LogProcessingRecord {
  id: number;
  tournament_id: number;
  tournament_name: string | null;
  attached_encounter_id: number | null;
  attached_encounter_name: string | null;
  filename: string;
  status: LogProcessingStatus;
  source: LogProcessingSource;
  uploader_name: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface LogHistoryResponse {
  items: LogProcessingRecord[];
  total: number;
}

export interface LogUploadItem {
  record_id: number;
  filename: string;
  attached_encounter_id: number | null;
}

export interface LogUploadError {
  filename: string | null;
  error: string;
}

export interface LogUploadResponse {
  uploaded: LogUploadItem[];
  errors: LogUploadError[];
}

export interface QueueDepth {
  name: string;
  messages_ready: number;
  messages_unacknowledged: number;
  consumers: number;
  status: "ok" | "not_found" | "error";
}

export interface LogStreamEvent {
  timestamp: string;
  queues: QueueDepth[];
  recent_logs: LogProcessingRecord[];
}

// ─── Bulk Operations ─────────────────────────────────────────────────────────

export interface CsvConfig {
  delimiter?: string;
  encoding?: string;
}

export interface BulkOperationResult {
  success: boolean;
  count: number;
  errors?: string[];
}

export type TournamentComputationJobStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "superseded";

export interface TournamentComputationJob {
  id: number;
  kind: "bracket" | "standings";
  operation: string;
  tournament_id: number;
  stage_id: number | null;
  stage_item_id: number | null;
  status: TournamentComputationJobStatus;
  payload_json: Record<string, unknown>;
  result_json: Record<string, unknown> | null;
  error: string | null;
  requested_by_user_id: number | null;
  idempotency_key: string;
  attempts: number;
  created_at: string;
  updated_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface CsvUserImportParams {
  battle_tag_row: number;
  discord_row: number | null;
  twitch_row: number | null;
  smurf_row: number | null;
  start_row?: number;
  delimiter?: string;
  has_discord?: boolean;
  has_smurf?: boolean;
  has_twitch?: boolean;
  sheet_url?: string;
}
