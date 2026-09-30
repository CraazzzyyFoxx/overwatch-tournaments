import { Team } from "@/types/team.types";
import { Encounter } from "@/types/encounter.types";
import { DivisionGridVersion } from "@/types/workspace.types";
import type { RosterShape, RosterSlotMap } from "@/lib/roster/shape";
import type { TournamentLink } from "@/types/stream.types";
import type { DraftFormatSettings } from "@/types/draft.types";

// ─── Enums ──────────────────────────────────────────────────────────────────

export type TournamentStatus =
  | "announcement"
  | "registration"
  | "draft"
  | "check_in"
  | "live"
  | "playoffs"
  | "completed"
  | "archived";

export type StageType =
  | "round_robin"
  | "single_elimination"
  | "double_elimination"
  | "swiss"
  | "ffa_league";

export type StageItemType = "group" | "bracket_upper" | "bracket_lower" | "single_bracket";

export type StageItemInputType = "final" | "tentative" | "empty";

export type EncounterResultStatus = "none" | "pending_confirmation" | "confirmed" | "disputed";


// ─── Team group ─────────────────────────────────────────────────────────────

/** The group a team played in: a `StageItem` of type `group`, name only. */
export interface TeamGroup {
  id: number;
  name: string;
}

// ─── Stage Model ────────────────────────────────────────────────────────────

export interface StageItemInput {
  id: number;
  stage_item_id: number;
  slot: number;
  input_type: StageItemInputType;
  team_id: number | null;
  source_stage_item_id: number | null;
  source_position: number | null;
}

export interface StageItem {
  id: number;
  stage_id: number;
  name: string;
  type: StageItemType;
  order: number;
  /** Per-group override of `Stage.advance_count`; `null` inherits the stage. */
  advance_count: number | null;
  inputs: StageItemInput[];
}

/** How a bracket stage orders its seeds; `slot` keeps the manual/standings order. */
export type SeedRanking = "slot" | "avg_sr" | "total_sr" | "random";

/**
 * A stage's series lengths. Precedence: `final` (an elimination stage's last
 * round) -> `by_round[round]` -> `default`. `by_round` keys are round numbers;
 * lower-bracket rounds are negative.
 */
export interface StageBestOfConfig {
  default: number;
  by_round: Record<string, number>;
  final: number | null;
}

/** One column an FFA game records. Mirrors `FfaColumn` of `ffa.types.ts`, which
 *  imports FROM this module — spelled out here rather than imported back. */
export interface StageFfaColumn {
  key: string;
  label: string;
  public: boolean;
  better: "higher" | "lower";
}

/** How an FFA league is scored, mirroring backend `FfaScoring`. */
export interface StageFfaScoring {
  /** What is entered per game, in table order. `[]` — places alone decide. */
  columns: StageFfaColumn[];
  /** What place `i + 1` is worth; a shorter list scores the tail at zero. */
  placement_points: number[];
  /** The expression a game's points are computed with, over the column keys
   *  plus `place`, `place_pts` and the lobby size (teams). */
  formula: string;
}

/** The rules a stage is played and ranked by. */
export interface StageRegulation {
  /** `null` = the preset the stage type picks. */
  ranking_preset: string | null;
  /** `null` = the preset's order. */
  tiebreak_order: string[] | null;
  /** A `null` member inherits the tournament's points. */
  scoring: { win: number | null; draw: number | null; loss: number | null };
  /** `null` = a bye pays the win points. */
  swiss_bye_points: number | null;
  de_grand_final_type: "no_reset" | "with_reset";
  seed_ranking: SeedRanking;
  best_of: StageBestOfConfig;
  ffa_scoring: StageFfaScoring;
}

export interface StageSummary extends StageRegulation {
  id: number;
  tournament_id: number;
  name: string;
  description: string | null;
  stage_type: StageType;
  max_rounds: number;
  advance_count: number | null;
  split_lower_bracket: boolean;
  order: number;
  is_active: boolean;
  is_published: boolean;
  is_completed: boolean;
  challonge_id: number | null;
  challonge_slug: string | null;
}

export interface Stage extends StageSummary {
  items: StageItem[];
}

// ─── Tournament ─────────────────────────────────────────────────────────────

/**
 * How a tournament forms its teams; each value has a `common.*` label.
 * `solo` is nominal: players register one by one for an FFA tournament and no
 * team is formed, so it has no flow of its own.
 */
export type TeamFormation = "balancer" | "draft" | "registration" | "solo";

interface TournamentPhaseSchedule {
  status: TournamentStatus;
  starts_at: string;
  ends_at: string | null;
}

export interface Tournament {
  id: number;
  created_at: Date;
  updated_at: Date | null;
  workspace_id: number;
  name: string;
  // Public-URL identity (`/tournaments/{slug}`); see lib/tournament/url.ts.
  slug: string;
  start_date: Date;
  end_date: Date;
  description: string | null;
  /**
   * Organizer-published regulations, Markdown. `null` means BOTH "nothing
   * published" and "this read did not opt into the `rules` entity" — only the
   * public tournament shell read (`getPublicOverview`) and the admin read ask
   * for it, because a multi-page document has no business riding in every
   * nested tournament of an encounter list.
   */
  rules: string | null;
  challonge_id: number | null;
  challonge_slug: string | null;
  is_league: boolean;
  is_finished: boolean;
  is_hidden: boolean;
  /** Free string on the backend; the known values are `TeamFormation`. */
  team_formation: string;
  status: TournamentStatus;
  auto_transitions_enabled: boolean;
  /**
   * Admits latecomers past the REGISTRATION window's `ends_at`, so an organizer
   * can keep the advertised closing date on the page instead of erasing it by
   * pushing `ends_at` out. Lifts `ends_at` ONLY — see `isRegistrationOpen`.
   */
  allow_late_registration: boolean;
  /**
   * Posts registration/check-in/match-time announcements to the workspace's
   * Discord notification channel.
   */
  discord_broadcasts_enabled: boolean;
  /**
   * Sends this tournament's personal notifications to players' Discord DMs.
   * The in-app inbox gets them either way.
   */
  discord_dms_enabled: boolean;
  phase_schedule: TournamentPhaseSchedule[];
  win_points: number;
  draw_points: number;
  loss_points: number;

  stages: StageSummary[];
  participants_count: number | null;
  registrations_count: number | null;
  teams_count: number | null;
  division_grid_version_id: number | null;
  division_grid_version: DivisionGridVersion | null;
  /** Tournament-level override of the roster shape; `null` = inherit. */
  roster_slots_json: RosterSlotMap | null;
  /** Draft format rule the wizard seeds every session with; `null` = snake. */
  draft_format_json: DraftFormatSettings | null;
  /** Resolved shape. `null` when the read did not opt into the entity. */
  roster_shape: RosterShape | null;
  /**
   * `true` while a draft session is in flight, i.e. while the write-path guard
   * would reject a roster-shape change. `null` on reads that did not opt in.
   */
  roster_locked_by_draft: boolean | null;
  /**
   * Active external links (Discord, VODs, bracket, rules), already ordered by
   * the backend. Optional rather than `| null`: the `links` entity is opt-in, so
   * the key is ABSENT on every read that did not ask for it — including
   * responses still sitting in a client cache from before this field existed.
   */
  links?: TournamentLink[];
  /** Wide banner for the tournament hero. Uploaded separately from the
   * settings PATCH (see `adminService.uploadTournamentImage`). */
  cover_image_url: string | null;
  /** Square-ish mark shown beside the tournament name. */
  logo_url: string | null;
}

/** Which of a tournament's two images an upload/delete targets. */
export type TournamentImageSlot = "cover" | "logo";

/**
 * Counts behind the public tournaments filter bar. Each group is counted with
 * the OTHER filters applied but its own dimension released, so a chip shows
 * how many rows selecting it would yield rather than how many it yields now.
 * `total`/`live` ignore every filter — they are the unfiltered headline.
 */
export interface TournamentFacets {
  total: number;
  /** `live` + `playoffs` combined: "matches happening right now". */
  live: number;
  by_status: Record<TournamentStatus, number>;
  league: number;
  standard: number;
}

// ─── Shared pick-ban vocabulary ─────────────────────────────────────────────


type MapVetoSessionStatus = "active" | "completed" | "cancelled";
type VetoSeedSource = "bracket_slot" | "standings" | "fallback_home" | "admin";


/**
 * Reason the room has no session yet (state responses with `session: null`).
 *
 * `slot_count_mismatch` (the bracket wants more maps than the config has slots)
 * and `slot_underfilled` (a slot in play has fewer than two candidates) both
 * describe a config that exists but disagrees with the bracket, so they must
 * not share the `not_configured` copy.
 */
export type VetoUnavailableReason =
  | "not_configured"
  | "teams_unknown"
  | "slot_count_mismatch"
  | "slot_underfilled"
  | "not_ready"
  /** Hero bans only: this round's map has not been picked yet, and heroes are
   * banned for a known map. Resolves on its own as the map phase progresses. */
  | "waiting_map"
  /** The bracket exists but its stage has not been activated yet — an
   * organizer preview, not a live match. Resolves once the organizer
   * activates the stage (`Stage.is_published`). */
  | "bracket_preview";


/** Side-agnostic step tokens stored on veto configs. */
export type VetoSequenceToken =
  "ban_first" | "ban_second" | "pick_first" | "pick_second" | "decider";

/** Which pool shape a pick-ban config uses. Mirrors the backend `MapVetoMode`. */
export type MapVetoMode = "pool" | "slots";


export interface Standings {
  id: number;
  tournament_id: number;
  team_id: number;
  stage_id: number | null;
  stage_item_id: number | null;
  position: number;
  overall_position: number;
  matches: number;
  win: number;
  draw: number;
  lose: number;
  points: number;
  /** The TRIMMED (median) Buchholz; `null` also marks a playoff row. */
  buchholz: number | null;
  /** Every opponent's points, nothing trimmed — a later, separate tiebreaker. */
  full_buchholz: number | null;
  /** Position of this row's tie-cluster head. Rows sharing a value were equal
   *  on every configured tiebreaker; their order was assigned, not earned. */
  tie_group: number | null;
  /** The organizer pinned this row's `position`; it holds through any later
   *  result or recalculation. A pinned row is never part of a `tie_group`. */
  is_pinned: boolean;
  tb: number | null;
  score_differential: number | null;
  ranking_context: Record<string, string | number | null> | null;
  tb_metrics: Record<string, number | null> | null;
  source_rule_profile: string | null;
  tiebreak_order: string[] | null;

  team: Team | null;
  tournament: Tournament | null;
  stage: Stage | null;
  stage_item: StageItem | null;
  matches_history: Encounter[];
}

// ─── Generic pick-ban engine (map + hero), ruleset v2 ───────────────────────
//
// Mirrors backend `PickBanSession`/`PickBanEntry`/`PickBanSubmission` and the
// state builder. Design + semantics: docs/plans/2026-09-28-pick-ban-constructor.md.

export type PickBanKind = "map" | "hero";
export type PickBanAction = "ban" | "pick" | "protect";
export type PickBanStepAction = PickBanAction | "decider";
export type PickBanEntryStatus = "available" | "picked" | "banned" | "protected";
export type PickBanSide = "home" | "away";

export interface PickBanEntry {
  id: number;
  item_id: number;
  round: number | null;
  order: number;
  action_index: number | null;
  picked_by: "home" | "away" | "decider" | null;
  protected_by: "home" | "away" | null;
  status: PickBanEntryStatus;
  team_id: number | null;
  /** Set when this entry is an active ban carried over from an earlier round
   * (the ban's `lifetime` still covers this map). Fixed: never undone here. */
  carried_from_round: number | null;
}

// ─── Ruleset (the constructor's document) ───────────────────────────────────

/** Achievements-style condition tree: `{}` is "always true". */
export type PickBanCondition =
  | Record<string, never>
  | { AND: PickBanCondition[] }
  | { OR: PickBanCondition[] }
  | { NOT: PickBanCondition }
  | { type: string; params: Record<string, unknown> };

export interface PickBanConstraint {
  type: string;
  params: Record<string, unknown>;
}

export type PickBanActors =
  | "first"
  | "second"
  | "both"
  | "home"
  | "away"
  | "winner_prev"
  | "loser_prev"
  | "system";
export type PickBanTimeoutPolicy = "random_fill" | "lock_draft" | "wait";
export type PickBanStepTarget = "opponent_player";
export type PickBanGenerator = "bracket" | "slot_veto";

export interface PickBanDisputeRule {
  enabled: boolean;
  /** How many times a revealed step may be reopened. */
  max: number;
}

export interface PickBanRulesetStep {
  id: string;
  action: PickBanStepAction;
  actors: PickBanActors;
  /** Items per acting side. */
  count: number;
  /** Items required to lock; null = `count`. */
  min: number | null;
  /** Drafts stay private until every acting side locked. */
  blind: boolean;
  target: PickBanStepTarget | null;
  /** Ban only: maps the ban stays active (1 = this map only); null = rest of series. */
  lifetime: number | null;
  /** null = inherit `PickBanRuleset.timer_seconds`. */
  timer_seconds: number | null;
  /** null = inherit `PickBanRuleset.on_timeout`. */
  on_timeout: PickBanTimeoutPolicy | null;
  dispute: PickBanDisputeRule;
  eligible: PickBanCondition;
  constraints: PickBanConstraint[];
}

export interface PickBanRulesetPhase {
  id: string;
  name: string | null;
  when: PickBanCondition;
  pool_filter: PickBanCondition;
  /** Map kind only; when set, `steps` is empty. */
  generator: PickBanGenerator | null;
  steps: PickBanRulesetStep[];
}

export interface PickBanRuleset {
  version: 2;
  timer_seconds: number | null;
  on_timeout: PickBanTimeoutPolicy;
  phases: PickBanRulesetPhase[];
}

/** One step as the session resolved it for a concrete round (`resolved_sequence_json`). */
export interface PickBanResolvedStep {
  index: number;
  round: number | null;
  phase_id: string;
  step_id: string;
  action: PickBanStepAction;
  /** `["system"]` for engine-resolved steps; `both` resolves to `[opener, other]`. */
  sides: (PickBanSide | "system")[];
  count: number;
  min: number;
  blind: boolean;
  target: PickBanStepTarget | null;
  lifetime: number | null;
  timer_seconds: number | null;
  on_timeout: PickBanTimeoutPolicy;
  dispute: PickBanDisputeRule;
  eligible: PickBanCondition;
  constraints: PickBanConstraint[];
}

export interface PickBanSubmissionItem {
  item_id: number;
  target_player_id: number | null;
}

export type PickBanSubmissionState = "draft" | "locked" | "revealed";

/** A submission the viewer may see: revealed ones, any of an open step, and the viewer's own drafts. */
export interface PickBanSubmission {
  step_index: number;
  side: PickBanSide | "system";
  attempt: number;
  state: PickBanSubmissionState;
  items: PickBanSubmissionItem[];
}

/** An opponent roster player a target step bans "for". */
export interface PickBanTarget {
  player_id: number;
  name: string;
  role: "tank" | "damage" | "support" | "flex" | null;
  sub_role: string | null;
  is_substitution: boolean;
}

export interface PickBanStepProgress {
  locked: boolean;
  /** Item count, reported even while the draft itself is hidden. */
  filled: number;
}

export interface PickBanEligible {
  item_ids: number[];
  /** Keyed by `PickBanTarget.player_id` when the step has a target. */
  by_target: Record<string, number[]> | null;
}

export interface PickBanDisputeState {
  /** Whether the VIEWER may reopen `step_index` right now. */
  available: boolean;
  step_index: number | null;
  attempts_used: number;
  max: number;
}

export interface PickBanSession {
  id: number;
  kind: PickBanKind;
  status: MapVetoSessionStatus;
  first_side: "home" | "away" | null;
  /** True once a result-dependent rotation needs `elect_opener` to proceed. */
  awaiting_choice: boolean;
  /** Only the loser of the round that triggered `awaiting_choice` may `elect_opener`. */
  pending_loser_side: "home" | "away" | null;
  seed_source: VetoSeedSource;
  home_seed: number | null;
  away_seed: number | null;
  /**
   * The reserve item each in-play slot named, snapshotted when the session
   * was created — same string-keyed-by-position contract as
   * `EncounterVetoSession.slot_reserves`. Always null for `kind: "hero"`
   * (no reserve concept there); read via `pickBanReserveMap`.
   */
  slot_reserves: Record<string, number> | null;
  started_at: string | null;
  current_step_started_at: string | null;
}

/**
 * Where one game (one position of the series) stands. `planned` is a position
 * whose map is not named yet; `awaiting_result` has a map and no accepted
 * score; `disputed` holds two claims that clash; `confirmed` carries the
 * accepted score, and only the admin correction command may change it.
 */
export type EncounterGameState =
  | "planned"
  | "awaiting_result"
  | "disputed"
  | "confirmed"
  | "cancelled";

/** Who put the accepted score on a game. A Match score is never one of them. */
export type GameResultSource = "captain_agreement" | "admin" | "admin_log";

/** One captain's independent claim of ONE game's score. */
export interface PickBanGameReport {
  side: "home" | "away";
  home_score: number;
  away_score: number;
}

/**
 * One position of the series, as the encounter's own result authority sees it.
 * `position` is 1-based in play order — a series may play the same map twice,
 * so the position, never `map_id`, is what identifies a game.
 */
export interface EncounterGame {
  id: number;
  position: number;
  map_id: number | null;
  state: EncounterGameState;
  /** Both null until the game is `confirmed`. */
  accepted_home_score: number | null;
  accepted_away_score: number | null;
  result_source: GameResultSource | null;
  result_version: number;
  confirmed_at: string | null;
}

/** A game inside the room, which also sees the claims behind its state. */
export interface PickBanGame extends EncounterGame {
  /** Both sides' claims, home first. Empty until a captain reports. */
  reports: PickBanGameReport[];
}

/**
 * The series score as the backend counts it: wins over confirmed games, with
 * `played` counting positions that reached a result (a draw settles one
 * without a win). `official` is set only once the encounter is finalized —
 * until then the live count is all there is.
 */
export interface PickBanSeries {
  home_wins: number;
  away_wins: number;
  played: number;
  complete: boolean;
  official: { home_score: number; away_score: number } | null;
}

/**
 * What both captains could agree to take back right now (`undo_state`): the
 * latest step with an applied captain item, plus every later step (a decider
 * resolved off its back, drafts of the step after it).
 *
 * `item_ids` empty means nothing is undoable — the only signal needed to decide
 * whether the affordance exists.
 */
export interface PickBanUndo {
  /** The side that already asked; null while nobody has, or once it landed. */
  requested_by: "home" | "away" | null;
  /** The resolved step the undo reopens. */
  step_index: number | null;
  /** Everything the undo reverts, in the order it was applied. */
  item_ids: number[];
  /** The reopened step's action. */
  action: PickBanAction | null;
  /** The step's single acting side; null for a multi-side step. */
  side: "home" | "away" | "decider" | null;
}

export interface PickBanState {
  session: PickBanSession | null;
  /** Set only when `session` is null — same contract as `EncounterMapPoolState.reason`. */
  reason?: VetoUnavailableReason;
  /** Whether each side's captain has confirmed readiness to begin the
   * encounter's pre-game phase — set regardless of `session`, so the room
   * can render "waiting for the other captain" even before a session exists. */
  readiness: { home: boolean; away: boolean };
  sequence: PickBanResolvedStep[];
  pool: PickBanEntry[];
  /** Visible submissions: revealed ones, any of an open step, the viewer's own drafts. */
  submissions: PickBanSubmission[];
  viewer_side: "home" | "away" | null;
  viewer_can_act: boolean;
  allowed_actions: PickBanAction[];
  current_step_index: number | null;
  current_step: PickBanResolvedStep | null;
  expected_action: PickBanStepAction | null;
  /** Non-system sides of the current step that have not locked yet. */
  acting_sides: PickBanSide[];
  /** Per side of the current step; null when no step is in play. */
  step_progress: Partial<Record<PickBanSide, PickBanStepProgress>> | null;
  /** ISO deadline of the current step's timer; null = no timer. */
  step_deadline: string | null;
  current_round: number | null;
  is_complete: boolean;
  /** What the VIEWER may choose on the current step; null when they cannot act. */
  eligible: PickBanEligible | null;
  /** Why the viewer's current draft cannot be locked yet; empty = lockable. */
  draft_issues: string[];
  /** Roster players per team when any resolved step targets a player. `home`
   * are the home team's players — the ones the away side bans for. */
  targets: { home: PickBanTarget[]; away: PickBanTarget[] } | null;
  dispute: PickBanDisputeState;
  /**
   * One entry per position of the series, `kind: "map"` only (a hero session
   * has no results of its own). Drives the loop's third phase: a map is
   * picked, its heroes are banned, then it is played and BOTH captains report
   * it against its GAME — and that confirmation is what opens the next map's
   * bans.
   */
  games?: PickBanGame[];
  /** The live series score over those games, and the official one once set. */
  series?: PickBanSeries;
  undo: PickBanUndo;
}

/** Only `"higher_seed"` exists today; kept as a union (not a literal) since
 * the backend models it as an extensible enum. */
type PickBanFirstPickRule = "higher_seed";
/**
 * Wider than the legacy veto config's `FirstBanRotation` (`fixed`|`alternate`
 * only, backed by its own narrower `tournament.firstbanrotation` PG enum) —
 * `PickBanConfig.first_ban_rotation` is backed by a separate
 * `tournament.pickbanrotation` PG enum that also carries the
 * result-dependent rotations the elect_opener flow needs.
 */
export type PickBanFirstBanRotation =
  "fixed" | "alternate" | "result_winner_first" | "result_loser_first" | "result_loser_choice";

/** One slot of a slot-mode `PickBanConfig`, as the admin CRUD serializer returns it. */
interface PickBanConfigSlot {
  position: number;
  reserve_item_id: number | null;
  candidates: number[];
}

export interface PickBanConfig {
  id: number;
  tournament_id: number;
  kind: PickBanKind;
  stage_id: number | null;
  round: number | null;
  mode: MapVetoMode;
  first_pick_rule: PickBanFirstPickRule;
  first_ban_rotation: PickBanFirstBanRotation;
  ruleset: PickBanRuleset;
  item_ids: number[];
  slots: PickBanConfigSlot[];
}

export interface PickBanConfigUpsertInput {
  kind: PickBanKind;
  stage_id?: number | null;
  round?: number | null;
  mode: MapVetoMode;
  first_pick_rule?: PickBanFirstPickRule;
  first_ban_rotation?: PickBanFirstBanRotation;
  ruleset: PickBanRuleset;
  item_ids?: number[];
  slots?: { candidates: number[]; reserve_item_id?: number | null }[];
}

// ─── Constructor catalog / validation / preview ─────────────────────────────

export type PickBanConditionContext = "round" | "item" | "pool";

export interface PickBanParamSpec {
  name: string;
  kind: "enum" | "int" | "bool" | "item_list" | "group_list" | "group";
  required: boolean;
  values: string[] | null;
  min: number | null;
  max: number | null;
  nullable: boolean;
}

export interface PickBanLeafSpec {
  type: string;
  contexts: PickBanConditionContext[];
  kinds: PickBanKind[];
  params: PickBanParamSpec[];
  /** Only valid in a step that has a `target`. */
  requires_target: boolean;
  /** Reads the acting side (`self`/`opponent`): not usable in a pool filter. */
  relative: boolean;
}

export interface PickBanConstraintSpec {
  type: string;
  params: PickBanParamSpec[];
  requires_target: boolean;
}

export interface PickBanPreset {
  id: string;
  kind: PickBanKind;
  modes: MapVetoMode[];
  ruleset: PickBanRuleset;
}

export interface PickBanRulesCatalog {
  leaves: PickBanLeafSpec[];
  constraints: PickBanConstraintSpec[];
  groups: { hero: string[]; map: string[] };
  presets: PickBanPreset[];
}

export interface PickBanRulesIssue {
  /** JSON-ish path, e.g. `phases[1].steps[0].count`. */
  path: string;
  code: string;
  severity: "error" | "warning";
  message: string;
}

export interface PickBanRulesValidation {
  valid: boolean;
  issues: PickBanRulesIssue[];
}

export interface PickBanPreviewMap {
  map_index: number;
  /** null when no phase matches this map. */
  phase_id: string | null;
  steps: PickBanResolvedStep[];
  max_new_bans: number;
  max_active_bans: number;
  /** Hero kind: per role, the fewest heroes that can be left; null for maps. */
  worst_case_remaining: Record<string, number> | null;
}

export interface PickBanRulesPreview {
  maps: PickBanPreviewMap[];
  issues: PickBanRulesIssue[];
}
