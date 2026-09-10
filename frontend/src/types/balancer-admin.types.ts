import type { PlayerRoleOption, PlayerRoleSlotCode } from "@/lib/player-role";
import type { Statistics as BalancerStatistics } from "@/types/balancer.types";
import type {
  Admission,
  BuiltInFieldConfig,
  CustomFieldDefinition,
  FieldValidationConfig,
  StatusKind,
  StatusMeta,
  StatusScope,
  SubroleCatalog,
  SubscriptionOutcome,
  SubscriptionRequirement,
} from "@/types/registration.types";

// Re-exported for callers that historically imported these registration
// field-config types from the admin module rather than registration.types
// directly (e.g. balancer/form/_components/formConfig.ts). The shapes are
// identical on both sides of the registration/admin boundary -- one
// registration form definition, read by both the public sign-up flow and
// this admin editor -- so registration.types.ts is the single source of
// truth and this file only re-exports.
export type { BuiltInFieldConfig, FieldValidationConfig };

/** Registration/draft wire code — the non-flex slice of `PlayerRoleSlotCode`. */
export type BalancerRoleCode = Exclude<PlayerRoleSlotCode, "flex">;
/** Capitalized roster key — the non-flex slice of `PlayerRoleOption`. */
export type BalancerRosterKey = Exclude<PlayerRoleOption, "Flex">;
export type BalancerRoleSubtype = string;
/** Layers a registration role's rank can resolve from, strongest first. */
export type RegistrationRankSource = "registration" | "workspace" | "ow" | "none";


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
  /** True when the registration's current custom status has excludes_from_ready set -- blocks the "ready" lane regardless of role-rank completeness. */
  ready_blocked: boolean;
  admin_notes: string | null;
}

export interface BalancerPlayerRoleEntry {
  role: BalancerRoleCode;
  subtype: BalancerRoleSubtype | null;
  priority: number;
  division_number: number | null;
  rank_value: number | null;
  /** "In play" — see `AdminRegistrationRole.is_active`. Read-only, never edited. */
  is_active: boolean;
  /** The organizer's checkbox. This is what a role toggle binds to. */
  is_declared_active: boolean;
  ow_rank_value: number | null;
  rank_source?: RegistrationRankSource;
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
  /** Stable per-role discomfort snapshot from the solver (immune to UI reordering). */
  all_discomforts?: Record<string, number>;
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

interface SavedBalancerTeam {
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

/** Rank-only re-export (balance or draft): nothing was created or removed. */
export interface RanksExportResponse {
  success: boolean;
  updated_players: number;
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

/** Response of `GET /api/balancer/tournaments/{id}/summary` (D29 tool-context resolver). */
export interface BalancerTournamentSummary {
  id: number;
  name: string;
  status: string;
  workspace_id: number;
}

/**
 * `xv-1` is the solver's own input contract (a file in this shape uploads
 * straight into a balance job); `owt-1` is our snapshot — the same player nodes
 * plus an `owt` block on each, and the roster shape the export was taken under.
 */
export type BalancerPlayerExportFormat = "xv-1" | "owt-1";

export interface BalancerPlayerExportResponse {
  format: string;
  players: Record<string, unknown>;
  generated_at?: string | null;
  source?: {
    tournament_id: number;
    tournament_name?: string | null;
    workspace_id?: number | null;
    player_key: string;
    scope: string;
    division_grid_version_id?: number | null;
  } | null;
  roster?: {
    slots: Record<string, number>;
    team_size: number;
    flex_slots: number;
    flex_role_mode: string;
  } | null;
}

export interface RegistrationUserExportResponse {
  processed: number;
  skipped: number;
  total: number;
}

type RegistrationRankAutofillPlayerStatus =
  | "will_update"
  | "applied"
  | "skipped"
  | "unchanged";

type RegistrationRankAutofillRoleAction =
  | "set"
  | "overwrite"
  | "keep_existing"
  | "unverified"
  | "missing_rank"
  | "blocked";

type RegistrationRankAutofillUsedSource =
  | "division_history"
  | "ow"
  | "analytics";

/** Individual source of a rank-autofill stage chain. */
export type RankAutofillSourceKey = "ow" | "division_history" | "analytics";

/**
 * Priority chains for rank autofill:
 *  - ow_first: OW (weekly composite) -> balancer (division history) -> analytics (past tournaments)
 *  - balancer_first: balancer -> analytics -> OW
 * Legacy presets; superseded by an explicit `stages` chain when one is supplied.
 */
type RegistrationRankAutofillMode = "ow_first" | "balancer_first";

/** One source in the autofill priority chain (order = list position). */
export interface RegistrationRankAutofillStage {
  source: RankAutofillSourceKey;
  enabled: boolean;
  /** Recency window for division_history / analytics, in tournaments (null = no limit). */
  lookback_tournaments?: number | null;
  /** Recency window for the OW source, in days (null = default 7-day window). */
  lookback_days?: number | null;
}

export interface RegistrationRankAutofillRequest {
  registration_ids?: number[] | null;
  overwrite_existing?: boolean;
  add_to_balancer?: boolean;
  /** Apply found role ranks even when other active roles have no parsed rank. */
  allow_partial?: boolean;
  /** Legacy preset; only used when `stages` is not supplied. */
  mode?: RegistrationRankAutofillMode;
  /** Explicit ordered priority chain; supersedes `mode` when non-empty. */
  stages?: RegistrationRankAutofillStage[];
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
  ow_rank_value: number | null;
  ow_current_rank_value: number | null;
  analytics_rank_value: number | null;
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
  /** Some active roles were filled but others had no parsed rank (allow_partial). */
  partial?: boolean;
  roles: RegistrationRankAutofillRole[];
}

export interface RegistrationRankAutofillResponse {
  total_registrations: number;
  updatable_registrations: number;
  applied_registrations: number;
  skipped_registrations: number;
  unchanged_registrations: number;
  /** Registrations with >=1 active role whose current rank no enabled source could corroborate. */
  unverified_registrations: number;
  role_updates: number;
  overwrite_existing: boolean;
  add_to_balancer: boolean;
  balancer_additions: number;
  players: RegistrationRankAutofillPlayer[];
}

export interface BalancerRegistrationRankHistoryEntry {
  tournament_id: number;
  tournament_name: string | null;
  role: BalancerRoleCode;
  rank_value: number;
}

export interface BalancerPlayerUpdateInput {
  role_entries_json?: BalancerPlayerRoleEntry[] | null;
  is_in_pool?: boolean | null;
  is_flex?: boolean | null;
  admin_notes?: string | null;
  registration_status?: string | null;
  registration_balancer_status?: string | null;
  pin?: boolean;
  clear_pin?: boolean;
}

export interface BalanceSaveInput {
  config_json?: Record<string, unknown> | null;
  result_json: InternalBalancePayload;
}

// ---------------------------------------------------------------------------
// Registration (admin)
// ---------------------------------------------------------------------------

// Identical shape to CustomFieldDefinition (registration.types.ts) -- one
// registration form definition, read by both the public sign-up flow and
// this admin editor.
export type AdminCustomFieldDef = CustomFieldDefinition;

export interface AdminRegistrationForm {
  id: number;
  tournament_id: number;
  workspace_id: number;
  is_open: boolean;
  auto_approve: boolean;
  require_open_profile?: boolean;
  open_profile_scope?: "main" | "all";
  show_ranks?: boolean;
  /** Extra ``is_substitute`` members per team. 0 disables the bench. */
  max_substitutes?: number;
  require_subscription?: boolean;
  /** WHEN the requirement blocks: `registration` refuses sign-up too, `check_in`
   *  (the default) only refuses at check-in. Ordered — `registration` implies both. */
  subscription_stage?: "registration" | "check_in";
  /** Server-resolved from the workspace requirement and read-only: the rule now
   *  lives on the workspace, so the upsert below deliberately has no counterpart.
   *  Still returned because the check-in dialog renders the composed rule. */
  subscription_requirement_json?: SubscriptionRequirement;
  built_in_fields: Record<string, BuiltInFieldConfig>;
  custom_fields: AdminCustomFieldDef[];
  subrole_catalog?: SubroleCatalog;
}

export interface AdminRegistrationFormUpsert {
  // No `is_open`: registration openness is the tournament's REGISTRATION
  // phase-schedule window, so the form cannot set it. The server ignores the
  // field if a stale client still sends it.
  auto_approve: boolean;
  require_open_profile?: boolean;
  open_profile_scope?: "main" | "all";
  show_ranks?: boolean;
  /** Extra is_substitute members per team. 0 disables the bench. */
  max_substitutes?: number;
  require_subscription?: boolean;
  subscription_stage?: "registration" | "check_in";
  built_in_fields: Record<string, BuiltInFieldConfig>;
  custom_fields: AdminCustomFieldDef[];
}

export interface AdminRegistrationRole {
  role: BalancerRoleCode;
  subrole: BalancerRoleSubtype | null;
  is_primary: boolean;
  priority: number;
  /**
   * Resolved by the roster engine, never the raw registration column: `null`
   * for a role it could not rate (with `rank_source: "none"`).
   */
  rank_value: number | null;
  /**
   * "In play", NOT "the organizer's checkbox": the role is declared active AND
   * the resolver found a rank for it. This is the ONE playability predicate —
   * anything asking "can this role be fielded" reads it and nothing else.
   * Never bind an editable toggle to it: an unrated role would flip its own
   * checkbox off. Use `is_declared_active` for that.
   */
  is_active: boolean;
  /** The raw `registration_role.is_active` column — what the organizer ticked. */
  is_declared_active: boolean;
  top_heroes?: string[] | null;
  /** Latest OW2 rank for this role, normalised to the workspace grid (from the backend). */
  ow_rank_value?: number | null;
  rank_source?: RegistrationRankSource;
}

/**
 * Role rows as SENT. `is_active` here writes the RAW declared column, which is
 * why the resolved read-only fields are absent: echoing `is_declared_active`,
 * `rank_source` or `ow_rank_value` back would be the client asserting the
 * resolver's own output as input.
 */
export type AdminRegistrationRoleInput = Omit<
  AdminRegistrationRole,
  "is_declared_active" | "rank_source" | "ow_rank_value"
>;

export type BalancerStatus = string;

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
  /** Only meaningful for scope === "balancer": whether a registration holding this status counts as part of the balancer pool. */
  excludes_from_balancer: boolean;
  /** Only meaningful for scope === "balancer": whether a registration holding this status is blocked from counting as "ready", independent of excludes_from_balancer. */
  excludes_from_ready: boolean;
  created_at: string;
  updated_at: string | null;
}

export interface BalancerCustomStatusCreateInput {
  scope: StatusScope;
  icon_slug?: string | null;
  icon_color?: string | null;
  name: string;
  description?: string | null;
  excludes_from_balancer?: boolean;
  excludes_from_ready?: boolean;
}

export interface BalancerCustomStatusUpdateInput {
  icon_slug?: string | null;
  icon_color?: string | null;
  name?: string | null;
  description?: string | null;
  excludes_from_balancer?: boolean | null;
  excludes_from_ready?: boolean | null;
}

export interface AdminRegistration {
  id: number;
  tournament_id: number;
  workspace_id: number;
  user_id: number | null;
  display_name: string | null;
  battle_tag: string | null;
  battle_tag_normalized: string | null;
  source: "manual" | "google_sheets";
  source_record_key: string | null;
  smurf_tags_json: string[];
  discord_nick: string | null;
  twitch_nick: string | null;
  boosty_nick?: string | null;
  stream_pov: boolean;
  /**
   * The roster engine's max rank across this registration's PLAYABLE roles,
   * `null` when none is playable. Read this instead of maxing `roles` client-
   * side: with `is_active` meaning playability, the two are the same number by
   * construction, and only one of them can drift.
   */
  best_rank: number | null;
  roles: AdminRegistrationRole[];
  notes: string | null;
  admin_notes: string | null;
  custom_fields_json: Record<string, unknown> | null;
  is_flex: boolean;
  status: string;
  status_meta: StatusMeta;
  balancer_status: BalancerStatus;
  balancer_status_meta: StatusMeta;
  /** Reason note for the current status, populated when balancer_status === "excluded".
   *  Whether the registration is actually excluded is read from
   *  balancer_status_meta.excludes_from_balancer, not a separate flag. */
  exclude_reason: string | null;
  checked_in: boolean;
  checked_in_at: string | null;
  checked_in_by_username: string | null;
  deleted_at: string | null;
  submitted_at: string | null;
  reviewed_at: string | null;
  reviewed_by_username: string | null;
  balancer_profile_overridden_at: string | null;
  /** Admission signals: sent by the registrations LIST read only, and only when
   *  the tournament's form requires them. Mutation responses omit them. */
  profiles_open?: boolean | null;
  subscription_outcome?: SubscriptionOutcome | null;
  /** The composed admission answer, identical in shape and content to the one
   *  the public participants read sends for the same registration. Required for
   *  the same reason as there: an optional field would put a defaulting branch
   *  back into every consumer. */
  admission: Admission;
}

export interface AdminRegistrationCreateInput {
  display_name?: string | null;
  battle_tag?: string | null;
  smurf_tags_json?: string[] | null;
  discord_nick?: string | null;
  twitch_nick?: string | null;
  boosty_nick?: string | null;
  stream_pov?: boolean;
  notes?: string | null;
  admin_notes?: string | null;
  /** Answers to the tournament's custom field definitions, keyed by field key. */
  custom_fields_json?: Record<string, string> | null;
  status?: string | null;
  balancer_status?: string | null;
  is_flex?: boolean;
  roles?: AdminRegistrationRoleInput[];
  /** Site account to anchor this registration on (its player). */
  auth_user_id?: number | null;
}

export interface AdminRegistrationUpdateInput {
  display_name?: string | null;
  battle_tag?: string | null;
  smurf_tags_json?: string[] | null;
  discord_nick?: string | null;
  twitch_nick?: string | null;
  boosty_nick?: string | null;
  notes?: string | null;
  admin_notes?: string | null;
  stream_pov?: boolean | null;
  /** Replaced wholesale when present; omit to leave the stored answers alone. */
  custom_fields_json?: Record<string, string> | null;
  is_flex?: boolean | null;
  status?: string | null;
  /** `ready`/`incomplete` are rejected server-side (computed from role ranks
   *  only); use `not_in_balancer`, `excluded`, or a custom slug. */
  balancer_status?: string | null;
  roles?: AdminRegistrationRoleInput[] | null;
  /** When set, (re)anchor the registration on this site account's player. */
  auth_user_id?: number | null;
  /** Only meaningful together with balancer_status === "excluded". */
  exclude_reason?: string | null;
  pin?: boolean;
  clear_pin?: boolean;
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

interface AdminGoogleSheetSyncError {
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

type MappingParserCardinality = "single" | "multi";

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
  subrole_catalog?: SubroleCatalog;
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
