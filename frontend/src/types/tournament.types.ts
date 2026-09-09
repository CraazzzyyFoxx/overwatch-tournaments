import { User } from "@/types/user.types";
import { Team } from "@/types/team.types";
import { Encounter } from "@/types/encounter.types";
import { DivisionGridVersion } from "@/types/workspace.types";
import type { RosterShape, RosterSlotMap } from "@/lib/roster-shape";
import type { TournamentLink } from "@/types/stream.types";

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

export type StageType = "round_robin" | "single_elimination" | "double_elimination" | "swiss";

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

export interface StageSummary {
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
  settings_json: Record<string, unknown> | null;
  challonge_id: number | null;
  challonge_slug: string | null;
}

export interface Stage extends StageSummary {
  items: StageItem[];
}

// ─── Tournament ─────────────────────────────────────────────────────────────

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
  // Public-URL identity (`/tournaments/{slug}`); see lib/tournament-url.ts.
  slug: string;
  start_date: Date;
  end_date: Date;
  description: string | null;
  challonge_id: number | null;
  challonge_slug: string | null;
  is_league: boolean;
  is_finished: boolean;
  is_hidden: boolean;
  team_formation: string;
  status: TournamentStatus;
  auto_transitions_enabled: boolean;
  /**
   * Admits latecomers past the REGISTRATION window's `ends_at`, so an organizer
   * can keep the advertised closing date on the page instead of erasing it by
   * pushing `ends_at` out. Lifts `ends_at` ONLY — see `isRegistrationOpen`.
   */
  allow_late_registration: boolean;
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


interface OwalStandingDay {
  tournament: Tournament;
  team: string;
  role: string;
  points: number;
  wins: number;
  draws: number;
  losses: number;
  win_rate: number;
}

export interface OwalStanding {
  user: User;
  role: string;
  division: number;
  days: Record<string, OwalStandingDay>;
  count_days: number;
  place: number;
  best_3_days: number;
  avg_points: number;
  wins: number;
  draws: number;
  losses: number;
  win_rate: number;
}

export interface OwalStandings {
  days: Tournament[];
  standings: OwalStanding[];
}

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

export interface OwalStack {
  user_1: User;
  user_2: User;
  games: number;
  avg_position: number;
}

// ─── Generic pick-ban engine (map + hero) ───────────────────────────────────
//
// Mirrors backend `PickBanSession`/`PickBanEntry`/`build_pick_ban_state`.


export type PickBanKind = "map" | "hero";
export type PickBanAction = "ban" | "pick" | "protect";
export type PickBanEntryStatus = "available" | "picked" | "banned" | "protected" | "played";

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
  turn_timer_seconds: number | null;
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

/** One captain's independent claim of ONE map's score (`EncounterMapReport`). */
export interface PickBanMapReport {
  map_id: number;
  /**
   * Which map OF THE SERIES the claim is for, 1-based in play order. This, not
   * `map_id`, is what a claim is matched against: a series may play the same
   * map twice, and keying on the map alone showed the earlier play's claims on
   * the later one. 0 when the encounter has no map pick-ban session at all.
   */
  map_index: number;
  side: "home" | "away";
  home_score: number;
  away_score: number;
}

/**
 * What both captains could agree to take back right now (`undo_state`).
 *
 * `item_ids` empty means nothing is undoable — the only signal needed to decide
 * whether the affordance exists. It can hold more than one id: a `decider` the
 * engine resolved off the back of the action is reverted with it, since undoing
 * the action alone would have the next read resolve the decider straight back.
 */
export interface PickBanUndo {
  /** The side that already asked; null while nobody has, or once it landed. */
  requested_by: "home" | "away" | null;
  /** Everything the undo reverts, in the order it was committed. */
  item_ids: number[];
  /** The primary action — the one a captain actually took. */
  action: PickBanAction | null;
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
  sequence: string[];
  pool: PickBanEntry[];
  viewer_side: "home" | "away" | null;
  viewer_can_act: boolean;
  allowed_actions: PickBanAction[];
  current_step_index: number | null;
  current_step: string | null;
  expected_action: PickBanAction | "decider" | null;
  turn_side: "home" | "away" | null;
  current_round: number | null;
  is_complete: boolean;
  /**
   * Per-map result claims filed for this encounter, `kind: "map"` only (a hero
   * session has no results of its own). Drives the loop's third phase: a map is
   * picked, its heroes are banned, then it is played and BOTH captains report
   * it — and that confirmation is what opens the next map's bans.
   */
  map_reports?: PickBanMapReport[];
  /**
   * The configured attribute-uniqueness rule (`"role"` or null), from
   * `PickBanConfig.unique_attribute_per_side_per_round`. The room greys out what
   * it forbids the side on the clock — see `attributeLocks`.
   */
  unique_attribute?: string | null;
  /**
   * Items the side on the clock may no longer BAN, because it already banned
   * them earlier in this series. Non-empty only under
   * `PickBanConfig.no_repeat_scope = "encounter_same_side"`, the one scope that
   * leaves them in the pool (one pool, two sides, only one of them barred) —
   * the room greys them out instead of letting a captain find out from the 400.
   */
  repeat_banned?: number[];
  /** Never absent in practice; optional for the same reason `map_reports` is —
   * a client reading an older payload must not crash on its absence. */
  undo?: PickBanUndo;
}

/** Side-agnostic step tokens, adds `protect_*` to the legacy veto vocabulary. */
export type PickBanSequenceToken =
  | "ban_first"
  | "ban_second"
  | "pick_first"
  | "pick_second"
  | "protect_first"
  | "protect_second"
  | "decider";

/** Only `"higher_seed"` exists today; kept as a union (not a literal) since
 * the backend models it as an extensible enum. */
type PickBanFirstPickRule = "higher_seed";
/** Cross-round BAN memory only — a protect is round-local and never recorded,
 * so it neither excludes nor is excluded. `encounter_same_side` excludes an
 * item only for the side that banned it — the opponent may still target it.
 * `encounter` excludes it for BOTH sides once anyone has. */
export type PickBanNoRepeatScope = "none" | "encounter" | "encounter_same_side";
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
  turn_timer_seconds: number | null;
  preset: string | null;
  sequence: PickBanSequenceToken[];
  no_repeat_scope: PickBanNoRepeatScope;
  /**
   * Only `"role"` is implemented server-side today; null disables the check.
   * Scoped per action kind: a side's bans constrain its bans and its protects
   * constrain its protects, never each other.
   */
  unique_attribute_per_side_per_round: string | null;
  allow_protect: boolean;
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
  preset?: string | null;
  turn_timer_seconds?: number | null;
  no_repeat_scope?: PickBanNoRepeatScope;
  unique_attribute_per_side_per_round?: string | null;
  allow_protect?: boolean;
  sequence?: PickBanSequenceToken[];
  item_ids?: number[];
  slots?: { candidates: number[]; reserve_item_id?: number | null }[];
}
