import type { Statistics as BalancerStatistics } from "@/types/balancer.types";

export type BalancerRoleCode = "tank" | "dps" | "support";
export type BalancerRosterKey = "Tank" | "Damage" | "Support";
export type BalancerRoleSubtype = string;
export type DuplicateResolution = "replace" | "skip";
export type DuplicateStrategy = "manual" | "replace_all" | "skip_all";

export interface BalancerTournamentSheet {
  id: number;
  tournament_id: number;
  source_url: string;
  sheet_id: string;
  gid: string | null;
  title: string | null;
  header_row_json: string[] | null;
  column_mapping_json: Record<string, unknown> | null;
  role_mapping_json: Record<string, BalancerRoleCode | null> | null;
  is_active: boolean;
  last_synced_at: string | null;
  last_sync_status: string | null;
  last_error: string | null;
}

export interface BalancerPlayerRecord {
  id: number;
  tournament_id: number;
  application_id: number;
  battle_tag: string;
  battle_tag_normalized: string;
  user_id: number | null;
  role_entries_json: BalancerPlayerRoleEntry[];
  is_flex: boolean;
  is_in_pool: boolean;
  admin_notes: string | null;
}

export interface BalancerPlayerHistoryRecord extends BalancerPlayerRecord {
  tournament_number: number | null;
}

export interface BalancerPlayerRoleEntry {
  role: BalancerRoleCode;
  subtype: BalancerRoleSubtype | null;
  priority: number;
  division_number: number | null;
  rank_value: number | null;
  is_active: boolean;
  ow_rank_value: number | null;
}

export interface BalancerApplication {
  id: number;
  tournament_id: number;
  tournament_sheet_id: number;
  battle_tag: string;
  battle_tag_normalized: string;
  smurf_tags_json: string[];
  twitch_nick: string | null;
  discord_nick: string | null;
  stream_pov: boolean;
  last_tournament_text: string | null;
  primary_role: string | null;
  additional_roles_json: string[];
  notes: string | null;
  submitted_at: string | null;
  synced_at: string;
  is_active: boolean;
  player: BalancerPlayerRecord | null;
}

export interface SheetSyncResponse {
  created: number;
  updated: number;
  deactivated: number;
  total: number;
  sheet: BalancerTournamentSheet;
}

export interface InternalBalancePlayer {
  uuid: string;
  name: string;
  assigned_rating: number;
  role_discomfort?: number;
  is_captain?: boolean;
  is_flex?: boolean;
  role_preferences: string[];
  sub_role?: BalancerRoleSubtype | null;
  all_ratings?: Record<string, number>;
}

export interface InternalBalanceTeam {
  id: number;
  name: string;
  average_mmr: number;
  rating_variance?: number | null;
  total_discomfort?: number | null;
  max_discomfort?: number | null;
  roster: Record<BalancerRosterKey, InternalBalancePlayer[]>;
}

export interface InternalBalancePayload {
  teams: InternalBalanceTeam[];
  statistics?: Partial<BalancerStatistics>;
  benched_players?: InternalBalancePlayer[];
}

export interface SavedBalancerTeam {
  id: number;
  balance_id: number;
  exported_team_id: number | null;
  name: string;
  balancer_name: string;
  captain_battle_tag: string | null;
  avg_sr: number;
  total_sr: number;
  roster_json: Record<string, unknown>;
  sort_order: number;
}

export interface SavedBalance {
  id: number;
  tournament_id: number;
  config_json: Record<string, unknown> | null;
  result_json: InternalBalancePayload;
  saved_by: number | null;
  saved_at: string;
  exported_at: string | null;
  export_status: string | null;
  export_error: string | null;
  teams: SavedBalancerTeam[];
}

export interface BalanceExportResponse {
  success: boolean;
  removed_teams: number;
  imported_teams: number;
  balance_id: number;
}

export interface BalancerTournamentConfig {
  id: number;
  tournament_id: number;
  workspace_id: number;
  config_json: Record<string, unknown>;
  updated_by: number | null;
  updated_at: string | null;
}

export interface BalancerTournamentConfigUpsertInput {
  config_json?: Record<string, unknown> | null;
}

export interface TournamentSheetUpsertInput {
  source_url: string;
  title?: string | null;
  column_mapping_json?: Record<string, unknown> | null;
  role_mapping_json?: Record<string, BalancerRoleCode | null> | null;
}

export interface BalancerPlayerCreateInput {
  application_ids: number[];
}

export interface BalancerPlayerImportDuplicate {
  battle_tag: string;
  battle_tag_normalized: string;
  application_id: number;
  existing_player_id: number;
  imported_role_entries_json: BalancerPlayerRoleEntry[];
  existing_role_entries_json: BalancerPlayerRoleEntry[];
  imported_is_in_pool: boolean;
  existing_is_in_pool: boolean;
  imported_admin_notes: string | null;
  existing_admin_notes: string | null;
}

export interface BalancerPlayerImportSkipped {
  battle_tag: string;
  battle_tag_normalized: string;
  reason: "missing_active_application" | "duplicate_in_file" | "no_ranked_roles";
}

export interface BalancerPlayerImportPreviewResponse {
  total_players: number;
  creatable_players: number;
  duplicate_players: number;
  skipped_players: number;
  duplicates: BalancerPlayerImportDuplicate[];
  skipped: BalancerPlayerImportSkipped[];
}

export interface BalancerPlayerImportResult {
  success: boolean;
  created: number;
  replaced: number;
  skipped_duplicates: number;
  skipped_missing_application: number;
  skipped_duplicate_in_file: number;
  skipped_no_ranked_roles: number;
  total_players: number;
}

export interface BalancerPlayerExportResponse {
  format: string;
  players: Record<string, unknown>;
}

export interface BalancerPlayerRoleSyncResponse {
  updated: number;
  skipped: number;
}

export interface ApplicationUserExportResponse {
  processed: number;
  skipped: number;
  total: number;
}

export interface RegistrationUserExportResponse {
  processed: number;
  skipped: number;
  total: number;
}

export type RegistrationRankAutofillPlayerStatus =
  | "will_update"
  | "applied"
  | "skipped"
  | "unchanged";

export type RegistrationRankAutofillRoleAction =
  | "set"
  | "overwrite"
  | "keep_existing"
  | "missing_rank"
  | "blocked";

export type RegistrationRankAutofillUsedSource =
  | "division_history"
  | "ow_peak"
  | "ow_current";

export interface RegistrationRankAutofillRequest {
  registration_ids?: number[] | null;
  overwrite_existing?: boolean;
  add_to_balancer?: boolean;
}

export interface RegistrationRankAutofillRole {
  role: BalancerRoleCode;
  current_rank_value: number | null;
  parsed_rank_value: number | null;
  action: RegistrationRankAutofillRoleAction;
  reason: string | null;
  platform: string | null;
  division: string | null;
  tier: number | null;
  season: number | null;
  captured_at: string | null;
  source: "analytics" | "balancer";
  division_history_rank_value: number | null;
  ow_peak_rank_value: number | null;
  ow_current_rank_value: number | null;
  ow_peak_season: number | null;
  used_source: RegistrationRankAutofillUsedSource | null;
}

export interface RegistrationRankAutofillPlayer {
  registration_id: number;
  display_name: string | null;
  battle_tag: string | null;
  status: RegistrationRankAutofillPlayerStatus;
  reason: string | null;
  will_add_to_balancer: boolean;
  balancer_reason: string | null;
  roles: RegistrationRankAutofillRole[];
}

export interface RegistrationRankAutofillResponse {
  total_registrations: number;
  updatable_registrations: number;
  applied_registrations: number;
  skipped_registrations: number;
  unchanged_registrations: number;
  role_updates: number;
  overwrite_existing: boolean;
  add_to_balancer: boolean;
  balancer_additions: number;
  players: RegistrationRankAutofillPlayer[];
}

export interface BalancerPlayerUpdateInput {
  role_entries_json?: BalancerPlayerRoleEntry[] | null;
  is_in_pool?: boolean | null;
  is_flex?: boolean | null;
  admin_notes?: string | null;
  registration_status?: string | null;
  registration_balancer_status?: string | null;
}

export interface BalanceSaveInput {
  config_json?: Record<string, unknown> | null;
  result_json: InternalBalancePayload;
}

// ---------------------------------------------------------------------------
// Registration (admin)
// ---------------------------------------------------------------------------

export interface AdminCustomFieldDef {
  key: string;
  label: string;
  type: "text" | "number" | "select" | "checkbox" | "url";
  required: boolean;
  placeholder: string | null;
  options: string[] | null;
  validation?: FieldValidationConfig | null;
}

export interface FieldValidationConfig {
  regex?: string | null;
  error_message?: string | null;
}

export interface BuiltInFieldConfig {
  enabled: boolean;
  required: boolean;
  /** Per-role subrole options. Only relevant for primary_role / additional_roles fields. */
  subroles?: Record<string, string[]>;
  validation?: FieldValidationConfig | null;
  /** `top_heroes` field only: max heroes selectable per role (default 5). */
  max_heroes?: number | null;
}

export interface SubroleOption {
  slug: string;
  label: string;
}

/** Workspace sub-role catalog keyed by registration role code (tank/dps/support). */
export type SubroleCatalog = Record<string, SubroleOption[]>;

export interface AdminRegistrationForm {
  id: number;
  tournament_id: number;
  workspace_id: number;
  is_open: boolean;
  auto_approve: boolean;
  opens_at: string | null;
  closes_at: string | null;
  require_open_profile?: boolean;
  open_profile_scope?: "main" | "all";
  show_ranks?: boolean;
  built_in_fields: Record<string, BuiltInFieldConfig>;
  custom_fields: AdminCustomFieldDef[];
  subrole_catalog?: SubroleCatalog;
}

export interface AdminRegistrationFormUpsert {
  is_open: boolean;
  auto_approve: boolean;
  opens_at?: string | null;
  closes_at?: string | null;
  require_open_profile?: boolean;
  open_profile_scope?: "main" | "all";
  show_ranks?: boolean;
  built_in_fields: Record<string, BuiltInFieldConfig>;
  custom_fields: AdminCustomFieldDef[];
}

export interface AdminRegistrationRole {
  role: BalancerRoleCode;
  subrole: BalancerRoleSubtype | null;
  is_primary: boolean;
  priority: number;
  rank_value: number | null;
  is_active: boolean;
  top_heroes?: string[] | null;
}

export type BalancerStatus = string;
export type StatusScope = "registration" | "balancer";
export type StatusKind = "builtin" | "custom";

export interface StatusMeta {
  value: string;
  scope: StatusScope;
  is_builtin: boolean;
  kind: StatusKind;
  is_override: boolean;
  can_edit: boolean;
  can_delete: boolean;
  can_reset: boolean;
  icon_slug: string | null;
  icon_color: string | null;
  name: string;
  description: string | null;
}

export interface BalancerCustomStatus {
  id: number;
  workspace_id: number | null;
  scope: StatusScope;
  slug: string;
  kind: StatusKind;
  is_override: boolean;
  can_delete: boolean;
  can_reset: boolean;
  icon_slug: string | null;
  icon_color: string | null;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface BalancerCustomStatusCreateInput {
  scope: StatusScope;
  icon_slug?: string | null;
  icon_color?: string | null;
  name: string;
  description?: string | null;
}

export interface BalancerCustomStatusUpdateInput {
  icon_slug?: string | null;
  icon_color?: string | null;
  name?: string | null;
  description?: string | null;
}

export interface AdminRegistration {
  id: number;
  tournament_id: number;
  workspace_id: number;
  auth_user_id: number | null;
  user_id: number | null;
  display_name: string | null;
  battle_tag: string | null;
  battle_tag_normalized: string | null;
  source: "manual" | "google_sheets";
  source_record_key: string | null;
  smurf_tags_json: string[];
  discord_nick: string | null;
  twitch_nick: string | null;
  stream_pov: boolean;
  roles: AdminRegistrationRole[];
  notes: string | null;
  admin_notes: string | null;
  custom_fields_json: Record<string, unknown> | null;
  is_flex: boolean;
  status: string;
  status_meta: StatusMeta;
  balancer_status: BalancerStatus;
  balancer_status_meta: StatusMeta;
  exclude_from_balancer: boolean;
  exclude_reason: string | null;
  checked_in: boolean;
  checked_in_at: string | null;
  checked_in_by_username: string | null;
  deleted_at: string | null;
  submitted_at: string | null;
  reviewed_at: string | null;
  reviewed_by_username: string | null;
  balancer_profile_overridden_at: string | null;
  profiles_open?: boolean | null;
}

export interface AdminRegistrationCreateInput {
  display_name?: string | null;
  battle_tag?: string | null;
  smurf_tags_json?: string[] | null;
  discord_nick?: string | null;
  twitch_nick?: string | null;
  stream_pov?: boolean;
  notes?: string | null;
  admin_notes?: string | null;
  is_flex?: boolean;
  roles?: AdminRegistrationRole[];
}

export interface AdminRegistrationUpdateInput {
  display_name?: string | null;
  battle_tag?: string | null;
  smurf_tags_json?: string[] | null;
  discord_nick?: string | null;
  twitch_nick?: string | null;
  stream_pov?: boolean | null;
  notes?: string | null;
  admin_notes?: string | null;
  is_flex?: boolean | null;
  status?: string | null;
  balancer_status?: string | null;
  roles?: AdminRegistrationRole[] | null;
}

export interface AdminRegistrationExclusionInput {
  exclude_from_balancer: boolean;
  exclude_reason?: string | null;
}

export interface AdminGoogleSheetFeed {
  id: number;
  tournament_id: number;
  source_url: string;
  sheet_id: string;
  gid: string | null;
  title: string | null;
  header_row_json: string[] | null;
  mapping_config_json: Record<string, unknown> | null;
  value_mapping_json: Record<string, unknown> | null;
  auto_sync_enabled: boolean;
  auto_sync_interval_seconds: number;
  last_synced_at: string | null;
  last_sync_status: string | null;
  last_error: string | null;
}

export interface AdminGoogleSheetFeedUpsertInput {
  source_url: string;
  title?: string | null;
  auto_sync_enabled?: boolean;
  auto_sync_interval_seconds?: number;
  mapping_config_json?: Record<string, unknown> | null;
  value_mapping_json?: Record<string, unknown> | null;
}

export interface AdminGoogleSheetSyncError {
  target: string | null;
  column: string | null;
  message: string;
  row_index?: number | null;
}

export interface AdminGoogleSheetFeedSyncResponse {
  created: number;
  updated: number;
  withdrawn: number;
  total: number;
  skipped: number;
  errors: AdminGoogleSheetSyncError[];
  feed: AdminGoogleSheetFeed;
}

export interface WorkspaceBalancerConfig {
  id: number;
  workspace_id: number;
  rank_delta_threshold: number | null;
  rank_delta_hide_from_pool: boolean;
  updated_by: number | null;
}

export interface WorkspaceBalancerConfigUpsert {
  rank_delta_threshold: number | null;
  rank_delta_hide_from_pool: boolean;
}

export interface AdminGoogleSheetMappingSuggestInput {
  source_url?: string | null;
}

export interface AdminGoogleSheetMappingSuggestResponse {
  headers: string[];
  mapping_config_json: Record<string, unknown>;
}

export interface AdminGoogleSheetMappingPreviewInput {
  source_url?: string | null;
  mapping_config_json?: Record<string, unknown> | null;
  value_mapping_json?: Record<string, unknown> | null;
}

export interface AdminGoogleSheetMappingPreviewResponse {
  headers: string[];
  sample_raw_row: Record<string, string>;
  parsed_fields: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Google Sheets mapping — catalog + multi-row preview (v2)
// ---------------------------------------------------------------------------

/** A single target the mapper can populate from the sheet. */
export type MappingTargetGroup = "identity" | "profile" | "roles" | "custom_fields";

export interface MappingTargetDef {
  key: string;
  label: string;
  group: MappingTargetGroup;
  accepted_parsers: string[];
  default_parser: string;
  default_mode: string;
  default_is_list: boolean;
  multi_column: boolean;
  required: boolean;
}

export type MappingParserCardinality = "single" | "multi";

export interface MappingParserDef {
  parser: string;
  label: string;
  cardinality: MappingParserCardinality;
  produces: string;
}

export type MappingValueCategoryName = "booleans" | "roles" | "subroles" | "role_subroles" | "divisions";

export interface MappingValueCategory {
  category: MappingValueCategoryName;
  entries: Record<string, unknown>;
}

export interface MappingCatalog {
  targets: MappingTargetDef[];
  parsers: MappingParserDef[];
  value_categories: MappingValueCategory[];
  custom_fields: AdminCustomFieldDef[];
  header_keys: string[];
}

/** A per-target validation error returned by PUT (422) / preview / sync. */
export interface MappingFieldError {
  target: string | null;
  column: string | null;
  message: string;
  code?: string;
}

export type MappingPreviewDisposition = "create" | "update" | "skip";

export interface MappingPreviewRow {
  row_index: number;
  sample_raw_row: Record<string, string>;
  parsed_fields: Record<string, unknown>;
  errors: MappingFieldError[];
  warnings: MappingFieldError[];
  disposition: MappingPreviewDisposition;
}

export interface MappingPreviewResponseV2 {
  headers: string[];
  header_keys: string[];
  rows: MappingPreviewRow[];
  create_count: number;
  update_count: number;
  skip_count: number;
  /** Back-compat single-row fields (preview row 0). */
  sample_raw_row: Record<string, string>;
  parsed_fields: Record<string, unknown>;
}

export interface AdminGoogleSheetMappingPreviewInputV2 extends AdminGoogleSheetMappingPreviewInput {
  sample_rows?: number;
}

/** Body returned by PUT `.../sheet` when the mapping is invalid (HTTP 422). */
export interface AdminGoogleSheetMappingValidationError {
  message: string;
  errors: MappingFieldError[];
}

// ---------------------------------------------------------------------------
// Local mapper UI state (not sent verbatim; serialized at save/preview)
// ---------------------------------------------------------------------------

export type MappingTargetMode = "columns" | "constant" | "disabled" | "auto";

export interface MappingTargetState {
  mode: MappingTargetMode;
  columns: string[];
  value?: string;
  parser?: string;
  is_list?: boolean;
}

export interface ValueMapRow {
  /** Stable client id so rows survive key edits without remounting inputs. */
  id: string;
  key: string;
  value: string;
}

export interface ValueMappingState {
  booleans: ValueMapRow[];
  roles: ValueMapRow[];
  subroles: ValueMapRow[];
  role_subroles: ValueMapRow[];
  divisions: ValueMapRow[];
}
