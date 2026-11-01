import type { Schema } from "@/types/api";
import type { CatalogEntityRead } from "@/types/catalog.types";
import { Team } from "@/types/team.types";
import {
  EncounterGame,
  EncounterResultSource,
  EncounterResultStatus,
  Stage,
  StageItem,
  Tournament,
} from "@/types/tournament.types";

/**
 * One incoming advancement edge: place `source_position` of `encounter_id`
 * fills seat `slot` of this encounter. The bracket's real topology, so a
 * reader can label an unresolved slot ("1st of M3") without inferring the
 * bracket's shape. Absent on a bracket generated before advancement edges
 * were recorded.
 */
export interface EncounterSlotSource {
  encounter_id: number;
  /** Place in the source encounter's final standing; 1 is first. */
  source_position: number;
  /** Seat of this encounter the edge fills, `1..slot_count`. */
  slot: number;
}

/**
 * One live or historical participation of an encounter (`encounter.team`). `id` is the
 * participation id every write addresses — a claim, a report and an admin
 * result all name it, never a slot. `team_id` goes null when the source team
 * is deleted; `name` is the snapshot that outlives it.
 */
export interface EncounterTeam {
  id: number;
  slot: number;
  team_id: number | null;
  name: string;
  seed: number | null;
  /** The standing inside the encounter: wins under a series, points in a lobby. */
  score: number;
  placement: number | null;
  active: boolean;
  /** The source team, expanded only where the read asks for it. */
  team?: Team | null;
}

/** A game as the public encounter read serves it: the position also names its
 * map, so a map can be pictured before (or without) a parsed log. The pick-ban
 * room's `PickBanGame` carries no map object — only `map_id`. */
export interface EncounterGameWithMap extends EncounterGame {
  map: Match["map"];
  /** The game's own mode, served with `map`; null until known. */
  mode: Schema<"tournament.EncounterGameRead">["mode"];
}

export interface Encounter {
  id: number;
  created_at: Date;
  updated_at: Date | null;
  /** Owner context: the tournament's or mix's workspace and discipline. */
  workspace_id: number;
  discipline: string;
  name: string;
  /** How many seats the card has: 2 is a duel, more is a lobby whose rows live in `FfaLobby`. */
  slot_count: number;
  /** How the card is scored: `points` is a lobby's card (a two-seat one included), `wins` a series. */
  scoring_preset: "wins" | "points";
  round: number;
  best_of: number;
  tournament_id: number;
  stage_id: number | null;
  stage_item_id: number | null;
  challonge_id: number | null;
  status: string;
  closeness: number | null;
  has_logs: boolean;
  result_status: EncounterResultStatus;
  /** Which writer decided the standing; null while no official result exists. */
  result_source: EncounterResultSource | null;
  /** Bumped by every result write; claims and reports name the version they were made against. */
  result_version: number;
  scheduled_at: Date | string | null;
  started_at: Date | string | null;
  ended_at: Date | string | null;
  current_map_index: number | null;
  // Every earlier decision lives in the result audit, not in a single slot
  // that only ever remembered the last writer.
  confirmed_at: Date | string | null;
  /**
   * When a completed encounter was played; null for every other one, and when the
   * stored stamps fall outside the tournament's dates (imported history), so
   * readers fall back to those dates.
   */
  played_at: string | null;
  /** The server's live definition; never re-derive it from the stamps. */
  is_live: boolean;
  /** In the last positive round of an elimination stage: the server's "final" (`is_final` filter). */
  is_final: boolean;
  /** Empty on a bracket whose advancement edges were never recorded. */
  sources?: EncounterSlotSource[];

  matches: Match[];
  /**
   * One entry per position of the series, in play order — the encounter's own
   * result authority. A `Match` row is a parsed log, a separate contract: the
   * two are rendered as two facts, never merged (spec §11).
   */
  games: EncounterGameWithMap[];
  /** The live seats, in slot order; retired participations are history. */
  teams: EncounterTeam[];
  tournament: Tournament;
  stage?: Stage | null;
  stage_item?: StageItem | null;
}

interface CaptainReportResult {
  encounter_team_id: number;
  score: number;
  placement: number | null;
  wins: number | null;
}

/** One participation's independent report of the finished encounter (`TeamReportRead`). */
export interface CaptainReport {
  id: number;
  encounter_id: number;
  /** The reporting participation. */
  encounter_team_id: number;
  reporter_user_id: number | null;
  /** Display name of the captain who filed it. */
  reporter_name?: string | null;
  /** Draws included; null only on a report carried over by the migration. */
  games_played: number | null;
  /** The `encounter.result_version` it was filed against. */
  basis_version: number;
  /** One line per live participation. */
  results: CaptainReportResult[];
  /** 1..10, or null when the tournament disables/does not require match quality. */
  closeness: number | null;
  comment: string | null;
  /** Organizer-defined text answers, keyed by `ReportCustomFieldDefinition.key`. */
  custom_fields: Record<string, string>;
  created_at: string | null;
  updated_at: string | null;
}

export interface ReportBuiltInFieldConfig {
  enabled: boolean;
  required: boolean;
}

export interface ReportCustomFieldDefinition {
  /** `^[a-z][a-z0-9_]{0,31}$`; the key under `CaptainReport.custom_fields`. */
  key: string;
  label: string;
  type: "text";
  required: boolean;
  placeholder: string | null;
}

/** Per-tournament configuration of the captain match-report form. */
export interface MatchReportForm {
  tournament_id: number;
  built_in_fields: {
    closeness: ReportBuiltInFieldConfig;
    map_codes: ReportBuiltInFieldConfig;
    comment: ReportBuiltInFieldConfig;
  };
  custom_fields: ReportCustomFieldDefinition[];
}

/**
 * One participation's replay code for one position (`ReplayCodeRead`, from
 * `game_team.replay_code`). The slot is the participation's own.
 */
export interface ReplayCode {
  position: number;
  encounter_team_id: number;
  code: string;
}

export interface CaptainReportsResponse {
  reports: CaptainReport[];
  /** Every participation's replay codes, in play order. */
  replay_codes: ReplayCode[];
  form: MatchReportForm;
}

/**
 * Mirrors the backend `DEFAULT_BUILT_IN_FIELDS`. Used while the reports query is
 * in flight so the dialog renders its usual shape instead of flashing empty and
 * then growing fields under the captain's cursor.
 */
export const DEFAULT_MATCH_REPORT_BUILT_INS: MatchReportForm["built_in_fields"] = Object.freeze({
  closeness: Object.freeze({ enabled: true, required: true }),
  map_codes: Object.freeze({ enabled: true, required: false }),
  comment: Object.freeze({ enabled: true, required: false })
});

export type RawSourceStatus = "available" | "missing" | "conflict" | "unverified";

/** One seat of a match: the encounter participation, its official result line and its observed whole-match team facts. */
export type MatchParticipant = Schema<"tournament.MatchParticipantRead">;

/** What a parsed log OBSERVED, with every participant (any number, `slot` order). Scores live in `participants`. */
export interface Match extends Omit<Schema<"tournament.MatchRead">, "map" | "encounter" | "raw_status"> {
  /**
   * Proven game's 1-based series position, never source order or an array
   * index. Null means the observation has no confirmed game binding.
   */
  map_index: number | null;
  raw_status: RawSourceStatus | null;
  /** Expanded by `entities=map`; its catalog mode is `map.parent`, the match's own mode is `mode`. */
  map: CatalogEntityRead | null;
  /** Expanded by `entities=encounter`. */
  encounter: Encounter | null;
}

/** One native observation of a stat: `workspace_member_id` null is a team fact, `entity_id` null has no entity grain. */
export type NativeFact = Schema<"tournament.NativeFact">;
/** `display` is how the match's game names the member (`display.canonical` builds the profile link); `handle_snapshot` is data. */
type NativeMatchMember = Schema<"tournament.NativeMatchMember">;
/** A child segment (a round); segment 0 is the whole match and has no row. */
type NativeSegment = Schema<"tournament.NativeSegment">;

/** A game's match filed by its id in the game's own records (`stats.match_fetch`), fetched and imported in the background. */
export type MatchImport = Schema<"tournament.MatchImportRead">;
export type MatchImportInput = Schema<"tournament.MatchImportInput">;

interface NativeMatchStatistics {
  /** Every observed member, event-only ones included. */
  members: NativeMatchMember[];
  segments: NativeSegment[];
  /** Facts at every grain; pick one with `selectFacts`, never add grains together. */
  facts: NativeFact[];
  /** Every catalog entity the facts name. */
  entities: CatalogEntityRead[];
}

export interface MatchWithStats extends Match {
  statistics: NativeMatchStatistics;
}

type EncounterScope = "all" | "my_team";

/** The list's status dimension: `upcoming` is open|pending and not live, server-side. */
export type EncounterStatusFilter = "live" | "upcoming" | "completed" | "open" | "pending";

export interface EncounterFilters {
  tournament_id?: number | null;
  stage_id?: number | null;
  stage_item_id?: number | null;
  best_of?: number | null;
  /** An `EncounterStatusFilter`; typed wide because the admin browser forwards its URL value as is. */
  status?: string | null;
  has_logs?: boolean | null;
  /** In the last positive round of an elimination stage. */
  is_final?: boolean | null;
  /** Completed, and the winning seat stood lower in the standings. */
  is_upset?: boolean | null;
  closeness_min?: number | null;
  closeness_max?: number | null;
  scope?: EncounterScope;
  sort?: string | null;
  /** One installed game's encounters; absent is every game. */
  discipline?: string | null;
}

/** A saved view's filter set (`EncounterFiltersRead`): `sort` is the page's own key, not a column. */
export interface EncounterSavedFilters extends Omit<EncounterFilters, "sort" | "discipline"> {
  query?: string | null;
  sort?: "date" | "closeness" | null;
}

export interface EncounterSavedView {
  id: number;
  workspace_id: number;
  name: string;
  filters: EncounterSavedFilters;
  sort_order: number;
}

/** `GET /encounters/overview`: the cheap counts, under the same filter params as the list. */
export interface EncounterOverview {
  counts: {
    /** The status segments: the current filters with the status dimension ignored. */
    all: number;
    live: number;
    upcoming: number;
    completed: number;
    /** The toggles: the current filters, status included, with that toggle forced on. */
    finals: number;
    upsets: number;
    with_logs: number;
    /** 0 for an anonymous viewer. */
    my_team: number;
  };
  /** Completed ∩ has_logs, status ignored. */
  completed_with_logs: number;
  /** Completed with `played_at` in the last 7 days, status ignored. */
  recent_completed: number;
  /** Up to 4 live encounters, status ignored. */
  live: Encounter[];
}

export type EncounterStageKind = "groups" | "playoffs" | "swiss" | "unassigned";

/**
 * `GET /encounters/insights`: completed encounters only, all time; every rate a fraction 0..1. The wire omits a null
 * field, hence the optional averages.
 */
export interface EncounterInsights {
  completed: number;
  avg_closeness?: number | null;
  /** 10 buckets of 0.1, each `[start, end)`; the last closes at 1. */
  closeness_histogram: { start: number; end: number; count: number }[];
  /** Completed duels, count desc; `winner == loser` is a draw. */
  score_lines: { winner: number; loser: number; count: number }[];
  /** Count desc; a kind with none is left out. */
  stage_kinds: { kind: EncounterStageKind; count: number }[];
  /** Top 6 played maps. */
  hot_maps: { name: string; count: number }[];
  /** Top 4 completed by closeness. */
  closest: Encounter[];
  avg_series_seconds?: number | null;
  /** Completed duels with `best_of > 1`: the base of the sweep and went-the-distance rates (a Bo1 is both). */
  multi_map: number;
  /** Multi-map completed duels won with the loser on 0. */
  sweeps: number;
  /** Multi-map completed duels whose seat scores sum to `best_of`. */
  went_distance: number;
}
