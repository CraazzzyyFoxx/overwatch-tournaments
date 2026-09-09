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

type RankCollectionScope = "registrations_only" | "all";

export interface RankCollectionConfig {
  enabled: boolean;
  interval_seconds: number;
  batch_size: number;
  rate_limit_per_minute: number;
  scope: RankCollectionScope;
  extra_accounts_per_registration: number;
  max_consecutive_failures: number;
  backoff_base_seconds: number;
  /** Self-pace each tick to cover the in-scope population once per interval. */
  auto_pace: boolean;
  /** Random spread on (re)schedule, fraction of the interval. 0 = exact. */
  jitter_fraction: number;
  /** Hard ceiling on per-tick claims under auto_pace. null = derive from rate budget. */
  max_per_tick: number | null;
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
  social_account_id: number;
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
  social_account_ids?: number[] | null;
}

export interface CollectTriggerResult {
  enqueued: number;
}

export interface RankFetchLogRow {
  id: number;
  social_account_id: number | null;
  /** Owning player id, resolved via the social account; null when deleted. */
  user_id: number | null;
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

// ─── Rank collection health stats (parser admin) ───────────────────────────────

interface RankStatusCounts {
  ok: number;
  pending: number;
  not_found: number;
  private: number;
  error: number;
  rate_limited: number;
  disabled: number;
}

export interface RankCollectionStats {
  total: number;
  never_checked: number;
  by_status: RankStatusCounts;
  tier0: number;
  tier1: number;
  tier2: number;
  coverage_24h: number;
  coverage_7d: number;
  last_success_at: string | null;
  fetch_24h: RankStatusCounts;
  fetch_24h_total: number;
  error_rate_24h: number;
  enabled: boolean;
  scope: string;
  interval_seconds: number;
  rate_limit_per_minute: number;
  /** OverFast instance the worker fetches from. */
  overfast_base_url: string;
  /** `closed` | `half_open` | `open` — open means no battle tag is being fetched at all. */
  overfast_circuit_state: string;
  /** Fetches rejected in 24h because the stored handle is not a battletag. */
  invalid_battle_tags_24h: number;
}

// ─── Subscription collection (parser admin) ────────────────────────────────────

interface SubscriptionStateCounts {
  active: number;
  inactive: number;
  unknown: number;
  /** Log-only: the check itself failed (provider outage), no verdict persisted. */
  error: number;
}

export interface SubscriptionCollectionStats {
  /** Entitlement rows tracked (workspace × user × provider). */
  total: number;
  tracked_users: number;
  never_checked: number;
  by_state: SubscriptionStateCounts;
  by_provider: Record<string, number>;
  coverage_24h: number;
  coverage_7d: number;
  last_success_at: string | null;
  last_check_at: string | null;
  checks_24h: SubscriptionStateCounts;
  checks_24h_total: number;
  error_rate_24h: number;
  active_tournaments: number;
  enabled: boolean;
  interval_seconds: number;
  batch_size: number;
}

export interface SubscriptionCheckLogRow {
  id: number;
  workspace_id: number | null;
  auth_user_id: number | null;
  /** Owning player id, resolved via auth_user_id; null when there is no profile. */
  user_id: number | null;
  user_name: string | null;
  provider: string;
  state: string;
  tier_rank: number | null;
  tier_label: string | null;
  /** What triggered the check: scheduled / registration / check_in / manual / redeem. */
  source: string;
  /** How it was proven: discord_role / twitch_helix / challenge_code / resolver. */
  mechanism: string | null;
  reason: string | null;
  error: string | null;
  created_at: string;
}

export interface SubscriptionCheckLogQuery {
  state?: string;
  source?: string;
  provider?: string;
  user_id?: number;
  before_id?: number;
  limit?: number;
}

export interface SubscriptionUserCollectionRow {
  workspace_id: number | null;
  workspace_name: string | null;
  provider: string;
  state: string;
  tier_rank: number | null;
  tier_label: string | null;
  source: string | null;
  checked_at: string | null;
  expires_at: string | null;
  reason: string | null;
}

export interface SubscriptionCollectTriggerInput {
  user_id?: number | null;
  providers?: string[] | null;
}

export interface SubscriptionCollectTriggerResult {
  checked: number;
}

export interface SubscriptionCollectionConfig {
  enabled: boolean;
  interval_seconds: number;
  batch_size: number;
}

// ─── Twitch stream poller ────────────────────────────────────────────────────

/** Value of the `stream.collection` setting. Backend bounds: interval 30..3600s,
 *  batch 1..100 (Helix `GET /streams` caps at 100 ids per call). */
export interface StreamCollectionConfig {
  enabled: boolean;
  interval_seconds: number;
  batch_size: number;
}

/** Outcome of the last poll tick. Mirrors the backend `StreamPollStatus` literal
 *  (and the `status` label on `stream_poll_ticks_total`) so the panel, the API and
 *  Grafana never disagree. */
export type StreamPollStatus =
  | "ok"
  | "empty"
  | "truncated"
  | "not_configured"
  | "rate_limited"
  | "unauthorized"
  | "unavailable"
  | "error";

/**
 * Poller health. Platform-wide, not per-workspace: there is one poller and one
 * Redis key, so the read wants the GLOBAL `stream.read` and carries no
 * `workspace_id`.
 */
export interface StreamPollHealth {
  /** The live config, echoed so the panel shows interval/batch next to the
   *  outcome they produced instead of reading the settings table separately. */
  enabled: boolean;
  interval_seconds: number;
  batch_size: number;
  /** `null` = no tick has been recorded yet — the scheduler has not reached a due
   *  tick. That is NOT a recorded failure, and the panel must not render it as
   *  one: a failure names what went wrong, never-ran names nothing. */
  status: StreamPollStatus | null;
  /** `null` for the same reason as `status`: no tick has been recorded yet. */
  last_run_at: string | null;
  tournaments_active: number | null;
  tournaments_updated: number | null;
  channels_polled: number | null;
  live_channels: number | null;
  /** Twitch's `Ratelimit-Remaining` at the last call, out of an 800/min bucket
   *  shared with identity-service's OAuth logins. */
  ratelimit_remaining: number | null;
  /** Twitch app credentials present in the worker's environment. Separates
   *  "operator never set them" from "Twitch refused them" (`unauthorized`). */
  credentials_configured: boolean;
}

// ─── Tournament ──────────────────────────────────────────────────────────────

import type { RosterSlotMap } from "@/lib/roster-shape";
import type {
  StageItemType,
  StageType,
  StageItemInputType,
  TournamentStatus
} from "@/types/tournament.types";

export interface TournamentCreateInput {
  workspace_id: number;
  name: string;
  description?: string;
  is_league: boolean;
  /** Public-URL slug; left blank, one is generated from `name`. */
  slug?: string;
  /** Lazy wizard drafts (D4) are created Unpublished and published later. */
  is_hidden?: boolean;
  status?: TournamentStatus;
  start_date: string;
  end_date: string;
  auto_transitions_enabled?: boolean;
  win_points?: number;
  draw_points?: number;
  loss_points?: number;
  division_grid_version_id?: number | null;
}

export interface TournamentUpdateInput {
  name?: string;
  description?: string | null;
  challonge_slug?: string | null;
  /** Renames the public-URL slug; the retired value keeps resolving via a redirect. */
  slug?: string | null;
  is_league?: boolean;
  is_finished?: boolean;
  is_hidden?: boolean;
  team_formation?: string;
  start_date?: string;
  end_date?: string;
  auto_transitions_enabled?: boolean;
  allow_late_registration?: boolean;
  win_points?: number;
  draw_points?: number;
  loss_points?: number;
  division_grid_version_id?: number | null;
  /** Roster shape override; `null` clears it back to the workspace default. */
  roster_slots_json?: RosterSlotMap | null;
}

export interface TournamentPhaseScheduleEntryInput {
  status: TournamentStatus;
  starts_at: string;
  ends_at?: string | null;
}

interface TournamentPreviewAccessUser {
  id: number;
  name: string;
  avatar_url?: string | null;
}

export interface TournamentPreviewAccessEntry {
  id: number;
  tournament_id: number;
  auth_user_id: number;
  created_at: string;
  user?: TournamentPreviewAccessUser | null;
}

export interface TournamentStatusTransitionInput {
  status: TournamentStatus;
  force?: boolean;
}

/**
 * Readiness aggregate for the hub living checklist (D13, §7.1).
 * Mirrors backend/app-service/src/services/dashboard/readiness.py. Field
 * groups are masked by the caller's permissions: `tournament.read` gates the
 * setup/bracket/logs group, `team.read` gates the registration/pool/balance/
 * draft group — a masked group arrives as `null` and the checklist renders
 * "no-access" instead of zeros (D16).
 */
export interface TournamentReadiness {
  tournament_id: number;
  status: TournamentStatus;
  team_formation: string;
  // visible with tournament.read:
  schedule_configured: boolean | null;
  grid_selected: boolean | null;
  stages_total: number | null;
  stage_slots_filled: boolean | null;
  bracket_generated: boolean | null;
  encounters_total: number | null;
  encounters_with_logs: number | null;
  logs_used: boolean | null;
  // visible with team.read:
  registration_form_configured: boolean | null;
  registration_open: boolean | null;
  registrations_pending: number | null;
  registrations_approved: number | null;
  registrations_checked_in: number | null;
  registrations_ranked: number | null;
  pool_ready: number | null;
  pool_need_fix: number | null;
  balance_saved: boolean | null;
  balance_exported_at: string | null;
  draft_session_status: string | null;
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

export interface StageBestOfConfig {
  default?: number;
  by_round?: Record<string, number>;
  final?: number | null;
}

export interface StageItemCreateInput {
  name: string;
  type: StageItemType;
  order?: number;
  advance_count?: number | null;
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

/**
 * One match of the bracket a stage would generate — `GET
 * /admin/stages/{id}/bracket-preview`, i.e. the real generator's skeleton.
 *
 * `local_id` is 1-based and skeleton-local, and `sources[].local_id` points at
 * another row of the same response rather than at an encounter, because these
 * matches have no encounter row yet.
 */
export interface StageBracketPreviewMatch {
  local_id: number;
  round: number;
  /** "A vs. B", with the wired teams' names when they are known. */
  name: string;
  best_of: number;
  home_team_id: number | null;
  away_team_id: number | null;
  sources: {
    local_id: number;
    role: "winner" | "loser";
    slot: "home" | "away";
  }[];
}


// ─── Team ────────────────────────────────────────────────────────────────────

export interface TeamCreateInput {
  name: string;
  tournament_id: number;
  captain_id?: number;
}

export interface TeamUpdateInput {
  name?: string;
  captain_id?: number;
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

/**
 * Statuses a plain field edit may set. Completion moves score, status,
 * result_status and the audit row together, so it has its own endpoint.
 */
export type EncounterEditableStatus = "OPEN" | "PENDING";

export interface EncounterSetResultInput {
  home_score?: number;
  away_score?: number;
  /** 1..10; defaults to the mean of the captain reports when omitted. */
  closeness?: number;
  /** Resolve a dispute by taking this team's report as the truth. */
  adopt_report_team_id?: number;
}

export interface EncounterResultRead {
  id: number;
  status: string;
  result_status: string;
  home_score: number;
  away_score: number;
  closeness: number | null;
  confirmed_at: string | null;
}

type EncounterResultAuditAction =
  | "confirm"
  | "reopen"
  | "auto_confirm"
  | "auto_dispute"
  | "import"
  | "cascade_reset";

export interface EncounterResultAuditRead {
  id: number;
  encounter_id: number;
  /** null = a machine actor (Challonge import, bracket cascade). */
  actor_user_id: number | null;
  actor_name: string | null;
  action: EncounterResultAuditAction;
  from_result_status: string | null;
  to_result_status: string;
  home_score_before: number | null;
  away_score_before: number | null;
  home_score_after: number;
  away_score_after: number;
  adopted_team_id: number | null;
  source: string;
  created_at: string;
}

/**
 * One captain's report inside an admin reports row. Mirrors the backend
 * `CaptainReportRead` — the same shape the public encounter read returns, plus
 * `reporter_name`.
 */
export interface AdminCaptainReport {
  id: number;
  encounter_id: number;
  team_id: number;
  side: "home" | "away" | null;
  reporter_user_id: number | null;
  reporter_name: string | null;
  home_score: number;
  away_score: number;
  /** `null` when the tournament disables or does not require match quality. */
  closeness: number | null;
  map_codes: Array<{ id: number; map_index: number; map_id: number | null; code: string }>;
  /** Free-form note from the captain; never part of dispute derivation. */
  comment: string | null;
  /** Organizer-defined text answers, keyed by the report form's field keys. */
  custom_fields: Record<string, string>;
  created_at: string | null;
  updated_at: string | null;
}

export interface EncounterReportsRow {
  id: number;
  name: string;
  tournament_id: number;
  tournament_name: string | null;
  stage_name: string | null;
  /** Lets the resolve dialog refuse a draw the finalizer would reject with a 400. */
  stage_type: string | null;
  round: number;
  best_of: number;
  status: string;
  result_status: string;
  scheduled_at: string | null;
  home_team: { id: number; name: string | null } | null;
  away_team: { id: number; name: string | null } | null;
  home_report: AdminCaptainReport | null;
  away_report: AdminCaptainReport | null;
  reported_count: number;
  /**
   * Three-valued on purpose: `null` until both sides have reported. "They
   * disagree" and "only one answered" call for different actions, so the UI
   * must not collapse them into a boolean.
   */
  scores_match: boolean | null;
  /** Advisory — reports predate per-round best-of, so a mismatch is a hint. */
  series_score_valid: boolean;
  last_resolution: {
    action: EncounterResultAuditAction;
    actor_user_id: number | null;
    actor_name: string | null;
    created_at: string;
  } | null;
}

export interface EncounterReportsStats {
  by_result_status: Record<string, number>;
  mismatch_count: number;
  awaiting_second_count: number;
}

/**
 * Filters shared by the list and its counters. The server applies the scope
 * fields to both but the chip fields only to the list, so a chip reports how
 * many rows it would select rather than how many it already has.
 */
export interface EncounterReportsQuery {
  workspace_id: number;
  page?: number;
  per_page?: number;
  query?: string;
  tournament_id?: number | null;
  stage_id?: number | null;
  result_status?: string[];
  mismatch_only?: boolean;
  reported_count?: number | null;
}

/**
 * The ingestion record a parsed match came from. Deliberately thinner than the
 * log console's own row: this is provenance for one map, not the log's
 * lifecycle.
 */
export interface LogRecordRef {
  id: number;
  filename: string;
  status: LogProcessingStatus;
  source: string | null;
  uploader_id: number | null;
  attempts: number;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

/** One parsed match — a single played map, as the log parser produced it. */
export interface AdminMatchRow {
  id: number;
  encounter_id: number;
  encounter_name: string;
  tournament_id: number;
  tournament_name: string;
  map_id: number;
  map_name: string;
  home_team: { id: number; name: string | null };
  away_team: { id: number; name: string | null };
  home_score: number;
  away_score: number;
  /** Map duration in seconds. */
  time: number;
  log_name: string;
  code: string | null;
  created_at: string;
  /**
   * `null` means provenance is unresolved. That is the normal state for the
   * bulk of the history — the ingestion table postdates most parsed matches —
   * so the UI must present it as unknown, never as a failure.
   */
  log_record: LogRecordRef | null;
}

export interface AdminMatchDetail extends AdminMatchRow {
  rounds: number;
  statistics_count: number;
  kill_feed_count: number;
  event_count: number;
}

export interface AdminMatchesQuery {
  workspace_id: number;
  page?: number;
  per_page?: number;
  query?: string;
  tournament_id?: number | null;
  encounter_id?: number | null;
  map_id?: number | null;
  log_status?: LogProcessingStatus[];
  unlinked_only?: boolean;
}

export interface EncounterCreateInput {
  tournament_id: number;
  stage_id: number | null;
  stage_item_id: number | null;
  home_team_id: number | null;
  away_team_id: number | null;
  round: number;
  home_score?: number;
  away_score?: number;
  /** COMPLETED is rejected: completion goes through setEncounterResult. */
  status?: EncounterEditableStatus;
  best_of?: number;
  name?: string;
}

export interface EncounterUpdateInput {
  stage_id?: number | null;
  stage_item_id?: number | null;
  home_team_id?: number | null;
  away_team_id?: number | null;
  home_score?: number;
  away_score?: number;
  /** COMPLETED is rejected: completion goes through setEncounterResult. */
  status?: EncounterEditableStatus;
  round?: number;
  name?: string;
  closeness?: number | null;
  best_of?: number;
  /** ISO instant, or `null` to clear the planned start time. */
  scheduled_at?: string | null;
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
  /** social_account ids on the source profile to move to the target. */
  social_account_ids: number[];
}

export interface UserMergeExecuteRequest extends UserMergePreviewRequest {
  preview_fingerprint: string;
  field_policy: UserMergeFieldPolicy;
  identity_selection: UserMergeIdentitySelection;
}

export interface UserMergeIdentityOption {
  id: number;
  provider: string;
  value: string;
  duplicate_on_target: boolean;
}

interface UserMergeUserSummary {
  id: number;
  name: string;
  avatar_url: string | null;
  social_accounts: UserMergeIdentityOption[];
  auth_links: number;
}

interface UserMergeConflictSummary {
  has_auth_conflict: boolean;
  summary: string | null;
}

interface UserMergeFieldOptions {
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

interface UserMergeIdentityResult {
  moved: number[];
  deduped: number[];
}

export interface UserMergeExecuteResponse {
  deleted_source_user_id: number;
  surviving_target_user_id: number;
  affected_counts: Record<string, number>;
  identity_results: UserMergeIdentityResult;
  audit_id: number;
}

// Unified social-account admin inputs
export interface SocialAccountCreateInput {
  provider: string;
  username: string;
  url?: string | null;
}

export interface SocialAccountUpdateInput {
  username?: string;
  url?: string | null;
}

export interface SocialVisibilityInput {
  workspace_id?: number | null;
  visible: boolean;
}

// ─── Hero ────────────────────────────────────────────────────────────────────

export interface HeroCreateInput {
  name: string;
  role: string;
  color?: string;
  image_path?: string;
  aliases?: string[];
}

export interface HeroUpdateInput {
  name?: string;
  role?: string;
  color?: string;
  image_path?: string;
  aliases?: string[];
}

// ─── Gamemode ────────────────────────────────────────────────────────────────

export interface Gamemode {
  id: number;
  created_at: Date;
  updated_at?: Date | null;
  name: string;
  aliases: string[];
}

export interface GamemodeCreateInput {
  name: string;
  aliases?: string[];
}

export interface GamemodeUpdateInput {
  name?: string;
  aliases?: string[];
}

// ─── Map ─────────────────────────────────────────────────────────────────────

export interface MapCreateInput {
  name: string;
  gamemode_id: number;
  in_competitive?: boolean;
  aliases?: string[];
}

export interface MapUpdateInput {
  name?: string;
  gamemode_id?: number;
  in_competitive?: boolean;
  aliases?: string[];
}

// ─── Catalog aliases ─────────────────────────────────────────────────────────

/** Catalog entity an alias (or an unresolved log name) belongs to. */
export type CatalogEntityType = "hero" | "map" | "gamemode";

/**
 * A name the log parser could not resolve. Upserted per `(entity_type,
 * raw_name)`, so `occurrences` counts how often the gap actually bites.
 */
export interface CatalogAliasMissRead {
  id: number;
  entity_type: CatalogEntityType;
  raw_name: string;
  occurrences: number;
  first_seen_at: string;
  last_seen_at: string;
  last_log_record_id: number | null;
  /** Owning tournament of `last_log_record_id`; null once the record is gone. */
  last_log_tournament_id: number | null;
  resolved_at: string | null;
}

export interface CatalogAliasMissQuery {
  page?: number;
  per_page?: number;
  entity_type?: CatalogEntityType;
  include_resolved?: boolean;
}

export interface CatalogAliasAttachInput {
  entity_type: CatalogEntityType;
  entity_id: number;
  alias: string;
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

// Every AchievementRule field except the ones tied to this specific
// installation (id, workspace_id, created_at, updated_at), which a portable
// import/export snapshot must not carry.
type AchievementRulePortable = Omit<AchievementRule, "id" | "workspace_id" | "created_at" | "updated_at">;

interface AchievementRuleExportWorkspace {
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

interface AchievementImportWarning {
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
  /**
   * Structured detail for the row. An import failure caused by unmapped teams
   * carries `missing_participant_ids`, which the integrations card groups on
   * rather than parsing `error_message`.
   */
  payload_json?: Record<string, unknown> | null;
  before_json?: Record<string, unknown> | null;
  after_json?: Record<string, unknown> | null;
  error_message: string | null;
}

// ─── Discord Channel Sync ─────────────────────────────────────────────────────

export interface DiscordChannelRead {
  id: number;
  tournament_id: number;
  channel_id: string;
  channel_name: string | null;
  is_active: boolean;
}

export interface DiscordChannelInput {
  channel_id: string;
  channel_name?: string | null;
  is_active: boolean;
}

// ─── Log Processing ───────────────────────────────────────────────────────────

export type LogProcessingStatus = "pending" | "processing" | "done" | "failed";
type LogProcessingSource = "upload" | "discord" | "manual";

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
  /** Times the record entered processing; >1 means the stall reaper requeued it. */
  attempts: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface LogHistoryResponse {
  items: LogProcessingRecord[];
  total: number;
}

/** Aggregate over the whole scope, not the page the console happens to show. */
export interface LogProcessingStats {
  total: number;
  pending: number;
  processing: number;
  done: number;
  failed: number;
  avg_duration_seconds: number | null;
  last_created_at: string | null;
}

interface LogUploadItem {
  record_id: number;
  filename: string;
  attached_encounter_id: number | null;
}

interface LogUploadError {
  filename: string | null;
  error: string;
}

export interface LogUploadResponse {
  uploaded: LogUploadItem[];
  errors: LogUploadError[];
}

// ─── Bulk Operations ─────────────────────────────────────────────────────────

export interface BulkOperationResult {
  success: boolean;
  count: number;
  errors?: string[];
}

type TournamentComputationJobStatus =
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


// ─── Platform audit log ──────────────────────────────────────────────────────

/** Curated set the backend writes today. `source` stays a `string` on the wire. */
export type AuditSource = "admin" | "api_key" | "challonge" | "discord" | "scheduler" | "system";

export interface AuditLogRead {
  id: number;
  created_at: string;
  /** `null` is a platform-level action with no owning workspace — superuser only. */
  workspace_id: number | null;
  /** `null` is a machine actor, not a missing one (FR3). */
  actor_auth_user_id: number | null;
  actor_label: string | null;
  /** `String(16)` from the whole platform, so an unrecognised value must render. */
  source: string;
  /** `String(64)`, not a closed enum — always render through `describeAuditAction`. */
  action: string;
  entity_type: string | null;
  entity_id: number | null;
  entity_label: string | null;
  /** Named domain fields the writer chose, never a raw request payload. */
  before_json: Record<string, unknown> | null;
  after_json: Record<string, unknown> | null;
  reason: string | null;
  ip_address: string | null;
  user_agent: string | null;
  correlation_id: string | null;
}

/** Whitelisted server-side; anything else is a 422 from the query model. */
export type AuditSortField =
  | "created_at"
  | "id"
  | "action"
  | "source"
  | "actor_label"
  | "entity_type";

export interface AuditLogQuery {
  workspace_id?: number | null;
  entity_type?: string | null;
  entity_id?: number | null;
  action?: string | null;
  actor_user_id?: number | null;
  page?: number;
  /** 1..200 server-side. */
  per_page?: number;
  sort?: AuditSortField | null;
  order?: "asc" | "desc";
  search?: string | null;
  /**
   * Client-side only (hence camelCase, unlike the wire params above): drops the
   * ambient `workspace_id` injection. The only way to reach platform rows
   * (`workspace_id IS NULL`), and a 422 for anyone but a superuser.
   */
  allWorkspaces?: boolean;
}