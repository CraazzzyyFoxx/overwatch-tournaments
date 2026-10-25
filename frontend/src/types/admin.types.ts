// Admin CRUD Types

import type { CaptainReport, MatchParticipant, RawSourceStatus, ReplayCode } from "@/types/encounter.types";
import type { RoleRef } from "@/lib/roster/role-ref";
import type { Schema } from "@/types/api";
import type { CatalogEntityRead, CatalogKind } from "@/types/catalog.types";

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

// ─── Rank collection status / manual trigger (parser admin) ────────────────────

export interface RankCollectionStatusRow {
  social_account_id: number;
  handle: string;
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
  handle: string;
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
  /** Upstream the worker fetches from (OverFast for Overwatch, the Riot API for League). */
  upstream_base_url: string;
  /** `closed` | `half_open` | `open` — open means no account is being fetched at all. */
  upstream_circuit_state: string;
  /** Fetches rejected in 24h because the stored handle is not valid for the game. */
  invalid_handles_24h: number;
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

/** One recorded poll tick, newest first from `GET /api/v1/streams/health/ticks`.
 *  Same outcome `StreamPollHealth` reports for the latest tick. */
export interface StreamPollTick {
  ran_at: string;
  status: StreamPollStatus;
  tournaments_active: number;
  tournaments_updated: number;
  channels_polled: number;
  live_channels: number;
  ratelimit_remaining: number | null;
}

// ─── Tournament ──────────────────────────────────────────────────────────────

import type { DraftFormatSettings } from "@/types/draft.types";
import type {
  StageItemType,
  StageRegulation,
  StageType,
  StageItemInputType,
  TournamentStatus
} from "@/types/tournament.types";

export interface TournamentCreateInput {
  workspace_id: number;
  /** The game the tournament is played in: always the creator's explicit choice. */
  discipline: string;
  name: string;
  description?: string;
  is_league: boolean;
  /** Public-URL slug; left blank, one is generated from `name`. */
  slug?: string;
  /** "Create tournament" creates it Unpublished; it is published from the hub. */
  is_hidden?: boolean;
  team_formation?: string;
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
  /** Published regulations, Markdown; `null` unpublishes them. */
  rules?: string | null;
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
  discord_broadcasts_enabled?: boolean;
  discord_dms_enabled?: boolean;
  logs_official?: boolean;
  pov_stream_delay_s?: number;
  win_points?: number;
  draw_points?: number;
  loss_points?: number;
  division_grid_version_id?: number | null;
  /** Draft format rule; `null` clears it back to snake. */
  draft_format_json?: DraftFormatSettings | null;
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
 * Mirrors backend/tournament-service/src/services/dashboard/readiness.py. Field
 * groups are masked by the caller's permissions: `tournament.read` gates the
 * setup/bracket/logs/standings group, `team.read` the registration/pool/
 * balance/draft group, `match.read` the result counts, `achievement.read` the
 * evaluation status — a masked group arrives as `null` and the checklist
 * renders "no-access" instead of zeros (D16).
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
  /** Duels only (`slot_count == 2`): a lobby never produces a match log. */
  duel_encounters_total: number | null;
  duel_encounters_with_logs: number | null;
  logs_used: boolean | null;
  standings_recalc_pending: boolean | null;
  // visible with team.read:
  registration_form_configured: boolean | null;
  registrations_pending: number | null;
  registrations_approved: number | null;
  registrations_checked_in: number | null;
  registrations_ranked: number | null;
  pool_ready: number | null;
  pool_need_fix: number | null;
  balance_saved: boolean | null;
  balance_exported_at: string | null;
  draft_session_status: string | null;
  // visible with match.read:
  results_overdue: number | null;
  results_pending_confirmation: number | null;
  results_disputed: number | null;
  // visible with achievement.read: "not_configured" | "none" | the latest evaluation run's status
  achievements_status: string | null;
}

// ─── Stage Admin ────────────────────────────────────────────────────────────

/** Each regulation field is optional; a sent field replaces that field whole. */
export interface StageCreateInput extends Partial<StageRegulation> {
  name: string;
  description?: string | null;
  stage_type: StageType;
  max_rounds?: number;
  advance_count?: number | null;
  advance_upper_count?: number | null;
  order?: number;
}

export interface StageUpdateInput extends Partial<StageRegulation> {
  name?: string;
  description?: string | null;
  stage_type?: StageType;
  max_rounds?: number;
  advance_count?: number | null;
  advance_upper_count?: number | null;
  order?: number;
}

export interface StageItemCreateInput {
  name: string;
  type: StageItemType;
  order?: number;
  advance_count?: number | null;
  advance_upper_count?: number | null;
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
  /** Moves the input into this item of the same stage. */
  stage_item_id?: number;
  /** Seed to insert at; the seeds it passes shift by one, both items stay 1..N. */
  slot?: number;
}

/** `POST /admin/encounters/{id}/swap-slot`: exchange the teams in two bracket seats. */
export interface EncounterSwapSlotInput {
  slot: number;
  target_encounter_id: number;
  target_slot: number;
}

/** One live seat as the bracket re-renders it after a swap. */
interface EncounterSeatState {
  id: number;
  slot: number;
  team_id: number | null;
  name: string;
}

interface EncounterSlotState {
  id: number;
  teams: EncounterSeatState[];
  name: string;
}

export interface EncounterSlotSwapRead {
  source: EncounterSlotState;
  target: EncounterSlotState;
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
  slot_count: number;
  /** The wired team of each seat in slot order, `null` while TBD. */
  team_ids: (number | null)[];
  sources: {
    local_id: number;
    /** Place in the source match's standing; 1 is first. */
    source_position: number;
    /** Seat of this match the edge fills, `1..slot_count`. */
    slot: number;
  }[];
}

/**
 * Where one slot of a template match gets its team: exactly one of `seed` or
 * `source_match` is set.
 *
 * `seed` is a placeholder label — `"U3"` is the third upper-bracket seed, `"L1"`
 * the first lower one — and `source_match` names another `TemplateMatch.id` in
 * the same template whose place `source_position` (1 = first) this slot takes.
 */
export type TemplateSlot =
  | { seed: string; source_match?: null; source_position?: null }
  | { source_match: number; source_position: number; seed?: null };

/** One seat of a template match: `slot` is numbered `1..n` the way the encounter seats it. */
type TemplateMatchSlot = TemplateSlot & { slot: number };

interface TemplateMatch {
  /** Template-local and stable across edits; not an encounter id. */
  id: number;
  /** Positive upstairs and in the finals, negative downstairs; never 0. */
  round: number;
  /** The whole card, numbered `1..n` with no gap. */
  slots: TemplateMatchSlot[];
}

/**
 * A stage's bracket drawn without teams — the blueprint every generation path
 * builds from. Order inside a round is the order of `matches`.
 */
export interface BracketTemplate {
  version: 1;
  upper_seeds: number;
  lower_seeds: number;
  matches: TemplateMatch[];
}

/** One reason a template was refused, from the PUT's 422 `problems` array. */
export interface TemplateProblem {
  match_id: number | null;
  slot: number | null;
  code: string;
  message: string;
}

/**
 * `GET/PUT/DELETE /admin/stages/{id}/bracket-template`.
 *
 * `custom` says whether the stage has a saved template; without one `template`
 * is what its format generates for `seeds` right now, or `null` when fewer than
 * two upper seeds are known and there is nothing to draw.
 */
export interface BracketTemplateRead {
  custom: boolean;
  template: BracketTemplate | null;
  seeds: { upper: number; lower: number };
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
  role: RoleRef | null;
  /** Omit or `null` for no rank; otherwise >= 1. */
  rank?: number | null;
  is_newcomer?: boolean;
  is_newcomer_role?: boolean;
  is_substitution?: boolean;
  related_player_id?: number | null;
}

export interface PlayerUpdateInput {
  name?: string;
  role?: RoleRef | null;
  /** Omitted = unchanged; `null` clears the rank. */
  rank?: number | null;
  is_newcomer?: boolean;
  is_newcomer_role?: boolean;
  is_substitution?: boolean;
  related_player_id?: number | null;
}

export interface PlayerSubRole {
  id: number;
  workspace_id: number;
  discipline: string;
  dimension: string;
  attrs: Record<string, unknown>;
  role: string;
  slug: string;
  label: string;
  description: string | null;
  sort_order: number;
  is_active: boolean;
}

export interface PlayerSubRoleCreateInput {
  workspace_id: number;
  discipline: string;
  role: string;
  label: string;
  slug?: string | null;
  description?: string | null;
  sort_order?: number;
  is_active?: boolean;
  icon?: string | null;
  color?: string | null;
}

export interface PlayerSubRoleUpdateInput {
  role?: string;
  label?: string;
  slug?: string | null;
  description?: string | null;
  sort_order?: number;
  is_active?: boolean;
  icon?: string | null;
  color?: string | null;
}

// ─── Encounter ───────────────────────────────────────────────────────────────

/**
 * Statuses a plain field edit may set. Completion moves score, status,
 * result_status and the audit row together, so it has its own endpoint.
 */
export type EncounterEditableStatus = "OPEN" | "PENDING";

/** One participation's line of an admin result. */
interface EncounterResultLineInput {
  encounter_team_id: number;
  score: number;
  placement?: number | null;
}

/** `POST /admin/encounters/{id}/result`: a reason is mandatory — an admin result overrides what the participants said. */
export interface EncounterSetResultInput {
  reason: string;
  /** One line per live participation; may be empty only with `adopt_report_team_id`. */
  results: EncounterResultLineInput[];
  /** 1..10; defaults to the mean of the participation reports when omitted. */
  closeness?: number;
  /** Resolve a dispute by taking this participation's report as the truth. */
  adopt_report_team_id?: number;
}

/** One participation's numbers inside a result snapshot. */
interface EncounterResultSnapshotLine {
  encounter_team_id: number;
  score: number;
  placement: number | null;
}

export interface EncounterResultRead {
  id: number;
  status: string;
  result_status: string;
  /** Which writer decided it; null while no official result exists. */
  result_source: string | null;
  result_version: number;
  /** The standing, one line per live participation, in slot order. */
  teams: EncounterResultSnapshotLine[];
  closeness: number | null;
  confirmed_at: string | null;
}

type EncounterResultAuditAction =
  | "confirm"
  | "reopen"
  | "auto_confirm"
  | "auto_dispute"
  | "auto_pending"
  | "import"
  | "cascade_reset"
  | "game_confirm"
  | "game_correct"
  | "game_cancel";

export interface EncounterResultAuditRead {
  id: number;
  encounter_id: number;
  /** The `encounter.result_version` this operation left behind. */
  result_version: number;
  /** null = a machine actor (Challonge import, bracket cascade). */
  actor_user_id: number | null;
  actor_name: string | null;
  action: EncounterResultAuditAction;
  from_result_status: string | null;
  to_result_status: string;
  /** `encounter` for the standing, `game` for one position's numbers. */
  snapshot_scope: "encounter" | "game";
  game_id: number | null;
  /** null when nothing preceded this row. */
  before: EncounterResultSnapshotLine[] | null;
  after: EncounterResultSnapshotLine[];
  adopted_team_id: number | null;
  reason: string | null;
  source: string;
  created_at: string;
}

/**
 * One line of the pre-game room's journal: the room's own events merged with
 * the encounter's result audit, newest first. `action` is open-ended on the
 * wire — an unknown one is rendered generically rather than dropped.
 */
export interface PregameRoomHistoryEntry {
  /** `"room:<id>"` / `"result:<id>"` — the two origins share no id space. */
  id: string;
  at: string;
  origin: "room" | "result";
  action: string;
  kind: "map" | "hero" | null;
  source: "captain" | "admin" | "system";
  /** The participation acted BY or FOR; null for room-level events. */
  encounter_team_id: number | null;
  actor_auth_user_id: number | null;
  /** null = the clock or a machine actor, rendered as "System". */
  actor_name: string | null;
  reason: string | null;
  data: Record<string, unknown>;
}

export interface PregameRoomHistoryRead {
  encounter_id: number;
  entries: PregameRoomHistoryEntry[];
}

/**
 * One participation's report inside an admin reports row. Mirrors the backend
 * `TeamReportRead` — the same shape the public encounter read returns.
 */
export type AdminCaptainReport = CaptainReport & { reporter_name: string | null };

/** One live seat of an encounter, as an admin list row names it. */
export interface EncounterParticipationRef {
  encounter_team_id: number;
  slot: number;
  team_id: number | null;
  name: string;
}

export interface EncounterReportsRow {
  id: number;
  name: string;
  tournament_id: number;
  tournament_name: string | null;
  stage_name: string | null;
  /** Lets the resolve dialog refuse a draw the finalizer would reject with a 400. */
  stage_type: string | null;
  /** The bracket round, or null for an encounter with no bracket position. */
  round: number | null;
  best_of: number;
  status: string;
  result_status: string;
  scheduled_at: string | null;
  /** The live seats, in slot order. */
  participations: EncounterParticipationRef[];
  /** Every report filed against it, one per reporting participation. */
  reports: AdminCaptainReport[];
  /** Every participation's replay codes, in play order — what the reports are compared against. */
  replay_codes: ReplayCode[];
  reported_count: number;
  /**
   * Three-valued on purpose: `null` until every participation has reported.
   * "They disagree" and "only some answered" call for different actions, so
   * the UI must not collapse them into a boolean.
   */
  standings_match: boolean | null;
  /** False when the reported standing is impossible for this encounter's rule. */
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

// ─── Pre-game rooms overview ─────────────────────────────────────────────────

/**
 * Where an encounter stands in the pre-game sequence, as the server decides it
 * (readiness → map veto → hero bans → per-map reports). `teams_unknown` is a
 * bracket slot nobody has filled yet; `idle` is "nothing is waiting on anyone".
 */
export type PregameRoomPhase =
  | "teams_unknown"
  | "readiness"
  | "map"
  | "hero"
  | "report"
  | "done"
  | "idle";

/** Why a row is listed as needing someone. Rendered as chips, never as prose. */
export type PregameRoomAttention =
  | "game_disputed"
  | "result_disputed"
  | "awaiting_choice"
  | "overdue"
  | "late_not_ready";

/**
 * One pick-ban kind of one encounter, flattened for the overview: enough to
 * say whose turn it is and how long they have had it, without the room's full
 * state. `status: null` means the kind is configured but no session exists —
 * `reason` then carries the server's `REASON_*` string for why not.
 */
export interface PregameKindSummary {
  status: "active" | "completed" | "cancelled" | null;
  reason: string | null;
  current_round: number | null;
  /** `null` when no step is open — a finished or blocked session. */
  step_index: number | null;
  step_count: number;
  step_action: string | null;
  step_blind: boolean;
  /** Participations (`EncounterTeam.id`) that still owe the open step an answer. */
  acting_team_ids: number[];
  step_started_at: string | null;
  /** `step_started_at` + the open step's timer, when that step has one. */
  deadline_at: string | null;
  awaiting_choice: boolean;
  /** Set while an organizer holds the session: no deadline, nobody may act. */
  paused_at: string | null;
}

/** One seat of the room (`encounter.team`), in slot order. */
interface PregameRoomTeam {
  encounter_team_id: number;
  slot: number;
  /** The source tournament team; null for a seat with none behind it. */
  team_id: number | null;
  name: string;
  score: number;
}

export interface PregameRoomRow {
  encounter_id: number;
  name: string;
  stage_id: number | null;
  stage_name: string | null;
  round: number;
  best_of: number;
  scheduled_at: string | null;
  status: string;
  result_status: string | null;
  /** The encounter's live seats, in slot order. */
  teams: PregameRoomTeam[];
  /** `EncounterTeam.id` (as a string) -> whether that captain confirmed readiness. */
  readiness: Record<string, boolean>;
  phase: PregameRoomPhase;
  /** `null` = the kind is not configured here and has no session either. */
  map: PregameKindSummary | null;
  hero: PregameKindSummary | null;
  /** Cancelled games are excluded from every count. */
  games: { total: number; confirmed: number; disputed: number; awaiting_result: number };
  attention: PregameRoomAttention[];
}

export interface PregameRoomsRead {
  tournament_id: number;
  generated_at: string;
  rooms: PregameRoomRow[];
}

/**
 * The ingestion record a parsed match came from. Deliberately thinner than the
 * log console's own row: this is provenance for one map, not the log's
 * lifecycle.
 */
export interface LogRecordRef {
  id: number;
  filename: string | null;
  status: LogProcessingStatus;
  source: string | null;
  uploader_id: number | null;
  attempts: number;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

/**
 * One parsed match — a single played map, as the log parser produced it. `participants` carries every seat with
 * its official result and observed team facts (`team_facts.score`); a deleted source team is `tournament_team_id: null`.
 */
export interface AdminMatchRow
  extends Omit<Schema<"tournament.AdminMatchRow">, "map" | "raw_status" | "log_record" | "participants"> {
  map: CatalogEntityRead;
  participants: MatchParticipant[];
  raw_status: RawSourceStatus | null;
  /** Null when no raw-log ingestion job is linked; not a processing failure. */
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
  /** One installed game's maps; `null`/absent is every game of the workspace. */
  discipline?: string | null;
}

/** One seat of a new encounter: which slot, and the team that takes it (`null` leaves it empty). */
interface EncounterSeatInput {
  slot: number;
  team_id: number | null;
}

export interface EncounterCreateInput {
  tournament_id: number;
  stage_id: number | null;
  stage_item_id: number | null;
  /** How many seats the card has; a duel is 2 (the default). */
  slot_count?: number;
  /** The seats to fill right away. */
  teams?: EncounterSeatInput[];
  round: number;
  /** COMPLETED is rejected: completion goes through setEncounterResult. */
  status?: EncounterEditableStatus;
  best_of?: number;
  name?: string;
}

/**
 * A field edit. Seats are not edited here: a seat changes hands through the
 * slot swap, and a standing is written only by the result writer.
 */
export interface EncounterUpdateInput {
  stage_id?: number | null;
  stage_item_id?: number | null;
  /** COMPLETED is rejected: completion goes through setEncounterResult. */
  status?: EncounterEditableStatus;
  round?: number;
  name?: string;
  closeness?: number | null;
  best_of?: number;
  /** ISO instant, or `null` to clear the planned start time. */
  scheduled_at?: string | null;
}

/** The observed score is the only editable team fact; participants are addressed by `encounter_team_id`. */
export interface MatchUpdateInput {
  map_id?: number;
  /** Seconds. */
  duration_s?: number | null;
  team_facts?: { encounter_team_id: number; stat_code: "score"; value: number }[];
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

interface AuthMergeOAuthDestination {
  connection_id: number;
  auth_user_id: number;
}

interface AuthMergeMembershipAction {
  workspace_id: number;
  action: "transfer" | "merge";
}

export interface AuthMergePolicy {
  surviving_auth_user_id: number;
  other_account_action: "keep" | "delete";
  oauth_destinations: AuthMergeOAuthDestination[];
  conflict_choices: Record<string, UserMergeFieldChoice>;
  membership_actions?: AuthMergeMembershipAction[];
}

interface AuthMergeMembership {
  workspace_id: number;
  auth_user_id: number;
  role_names: string[];
  can_merge: boolean;
}

interface AuthMergeRole {
  id: number;
  name: string;
  workspace_id: number | null;
}

interface AuthMergeDeny {
  permission_id: number;
  workspace_id: number | null;
  resource: string;
  action: string;
  reason: string | null;
}

interface AuthMergeAccount {
  id: number;
  username: string;
  email: string;
  has_password: boolean;
  is_active: boolean;
  is_superuser: boolean;
  roles: AuthMergeRole[];
  denies: AuthMergeDeny[];
}

interface AuthMergeOAuthConnection {
  id: number;
  provider: string;
  provider_user_id: string;
  username: string;
  auth_user_id: number;
}

interface AuthMergeDataConflict {
  key: string;
  resource: string;
  label: string;
  source_value: unknown;
  target_value: unknown;
}

export interface AuthMergePreview {
  accounts: AuthMergeAccount[];
  oauth_connections: AuthMergeOAuthConnection[];
  policy: AuthMergePolicy;
  resource_counts: Record<string, number>;
  data_conflicts: AuthMergeDataConflict[];
  permission_changes: boolean;
  memberships?: AuthMergeMembership[];
  issues: string[];
  state_fingerprint: string;
}

interface AuthMergeResult {
  surviving_auth_user_id: number;
  deleted_auth_user_id: number | null;
  moved_oauth_connection_ids: number[];
  transferred_counts: Record<string, number>;
}

export interface UserMergePreviewRequest {
  source_user_id: number;
  target_user_id: number;
  auth_policy?: AuthMergePolicy | null;
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
  confirm_auth_changes: boolean;
  confirm_auth_deletion: boolean;
  confirm_permission_changes: boolean;
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
  auth_user_id: number | null;
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
  auth_merge: AuthMergePreview | null;
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
  auth_merge: AuthMergeResult | null;
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

// ─── Catalog aliases ─────────────────────────────────────────────────────────

/** `character|map|mode` are catalog entities an alias can name; `stat|event|role` are undeclared module codes. */
export type CatalogAliasMissKind = CatalogKind | "stat" | "event" | "role";

/**
 * One unresolved name as the API sends it. Upserted per `(discipline, kind, raw_name)`, so `occurrences` counts how
 * often the gap actually bites. A `role` miss carries `dimension:role` as its `raw_name`.
 */
export interface CatalogAliasMissRead {
  id: number;
  discipline: string;
  kind: CatalogAliasMissKind;
  raw_name: string;
  occurrences: number;
  first_seen_at: string;
  last_seen_at: string;
  last_ingest_job_id: number | null;
  /** Hinted tournament of `last_ingest_job_id`; null when the job carried no hint or is gone. */
  last_log_tournament_id: number | null;
  resolved_at: string | null;
}

export interface CatalogAliasMissQuery {
  page?: number;
  per_page?: number;
  discipline?: string;
  kind?: CatalogAliasMissKind;
  include_resolved?: boolean;
}

export interface CatalogAliasAttachInput {
  entity_id: number;
  alias: string;
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
  discipline: string;
  entity_id: number | null;
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
  discipline: string;
  entity_id?: number | null;
  category: AchievementCategory;
  scope: AchievementScope;
  grain: AchievementGrain;
  condition_tree: Record<string, unknown>;
  depends_on?: string[];
  enabled?: boolean;
  min_tournament_id?: number | null;
}

/** An edit never carries `discipline` (immutable) and never `hero_id` (retired); the server rejects both. */
export interface AchievementRuleUpdateInput {
  slug?: string;
  name?: string;
  description_ru?: string;
  description_en?: string;
  image_url?: string | null;
  entity_id?: number | null;
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
  /** Portable format v2 (`discipline` + `entity_id`); v1 and `hero_id` files are refused by the server. */
  schema_version: 2;
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
  status: "queued" | "running" | "done" | "partial" | "failed";
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
  /** Source tables the node reads; a rule's `depends_on` is their union. */
  depends_on: string[];
  /** Only valid inside a `team_players_match`/`captain_property` sub-tree. */
  subcondition_only: boolean;
  /** Valid there in addition to the top level. */
  subcondition_ok: boolean;
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

export type LogProcessingStatus = "pending" | "processing" | "awaiting_link" | "done" | "failed";

export interface LogProcessingRecord {
  id: number;
  tournament_id: number | null;
  tournament_name: string | null;
  attached_encounter_id: number | null;
  attached_encounter_game_id: number | null;
  attached_encounter_name: string | null;
  filename: string;
  status: LogProcessingStatus;
  source: string;
  raw_status: RawSourceStatus;
  raw_available: boolean;
  uploader_name: string | null;
  /** The human message of `error` (or the historical text itself). */
  error_message: string | null;
  /** Structured failure/awaiting explanation; historical text reads as code `historical`. */
  error: LogIngestError | null;
  /** Times the record entered processing; >1 means the stall reaper requeued it. */
  attempts: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  /** Revision of the observation this job is the evidence for; null while it is not. Reparse sends it back. */
  observation_revision: number | null;
  /** True while this job is the current provenance of its game's observation. */
  is_current_provenance: boolean;
  /** Document teams in canonical order, awaiting_link only: the bind team map is keyed by `key`. */
  teams: LogDocumentTeam[];
}

interface LogIngestIssue {
  path: (string | number)[];
  code: string;
  message: string;
  kind?: string | null;
  raw_name?: string | null;
}

interface LogIngestError {
  code: string;
  message: string;
  issues: LogIngestIssue[];
}

interface LogDocumentTeam {
  key: string;
  source_position: number;
  participants: string[];
}

export interface LogRetryRequest {
  encounter_id?: number | null;
  encounter_game_id?: number | null;
  /** Explicit reparse of a done job; requires `expected_revision` and never re-attaches. */
  reparse?: boolean;
  expected_revision?: number;
}

/** Maps every document team key to the `encounter.team` id seated in the game. */
export interface LogBindRequest {
  encounter_game_id: number;
  teams: Record<string, number>;
  /** 0 = the game has no observation, n = replace exactly revision n; required when it is occupied. */
  expected_revision?: number;
}

/** Machine codes of a refused bind/reparse/retry (`ApiError.details[].code`). */
export type LogOperationErrorCode =
  | "expected_revision_required"
  | "stale_revision"
  | "stale_binding"
  | "binding_mismatch"
  | "identity_conflict"
  | "invalid_team_map"
  | "binding_target_not_found"
  | "ingest_busy"
  | "ingest_pending"
  | "reparse_required"
  | "job_not_done";

/** Unoccupied: `match_id`/`ingest_job_id` null and `revision` 0. Historical observations are never replaceable. */
export interface GameObservationRead {
  encounter_game_id: number;
  match_id: number | null;
  revision: number;
  ingest_job_id: number | null;
  is_historical: boolean;
}

/** `IngestJobRead` as the bind endpoint commits it. */
export interface LogBindResponse {
  id: number;
  status: LogProcessingStatus;
  error: LogIngestError | null;
  binding: { encounter_game_id: number; match_id: number; revision: number } | null;
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
  awaiting_link: number;
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
  /** ISO timestamp: only rows created at or after it. */
  since?: string | null;
  /** Drops one actor's rows; machine rows (no actor) stay. */
  exclude_actor_user_id?: number | null;
  /** Comma-separated `AuditSource` values; an unknown one is a 422. */
  source?: string | null;
  /**
   * Client-side only (hence camelCase, unlike the wire params above): drops the
   * ambient `workspace_id` injection. The only way to reach platform rows
   * (`workspace_id IS NULL`), and a 422 for anyone but a superuser.
   */
  allWorkspaces?: boolean;
}
