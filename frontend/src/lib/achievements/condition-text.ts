"use client";

/**
 * One source of human-readable text for the achievement condition DSL.
 *
 * The engine stores conditions as `{AND|OR|NOT}` groups over `{type, params}`
 * leaves, where the params mean nothing on their own ("op >= value 5",
 * "min_time 600"). Everything that renders a condition - the public "How to
 * earn" list, the public diagram, the admin read-only viewer and its outline -
 * goes through here, so a node reads the same sentence everywhere and a new
 * backend node only needs one message key.
 *
 * Messages live under `achievements.conditionText.*`; an unknown node falls
 * back to its catalogue label plus its raw params, which is still readable.
 */
import { useCallback, useMemo } from "react";
import { useTranslations } from "next-intl";

import { useCatalogEntities } from "@/hooks/useCatalogEntities";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useRoleName } from "@/hooks/useRoleName";
import { findRole, ratedDimension } from "@/lib/roster/ontology";
import type { WorkspaceAxis } from "@/lib/site/discipline-scope";
import type { ConditionNode } from "@/types/achievement.types";

/**
 * Loose view of next-intl's translator. Keys here are built from engine node
 * names, which the statically typed `t` cannot know.
 */
export interface ConditionTranslator {
  (key: string, values?: Record<string, string | number>): string;
  has(key: string): boolean;
}

export interface ConditionTextOptions {
  t: ConditionTranslator;
  /** Display name for a hero slug; defaults to a humanized slug. */
  heroName?: (slug: string) => string;
  /**
   * Display name for a role code of the rule's game (its ontology), `null` when the game does not know it. The
   * engine compares role params lower-cased, so the code passed here is too.
   */
  roleName?: (code: string) => string | null;
}

/** A condition rendered as prose: a group heading with children, or one leaf. */
export interface ConditionSentence {
  /** Set on group rows only. */
  group?: "AND" | "OR" | "NOT";
  text: string;
  children?: ConditionSentence[];
}

const NS = "achievements.conditionText";

/** The leaf a node with no type falls back to - the engine's "this map" predicate. */
export const DEFAULT_CONDITION_TYPE = "match_win";

type Params = Record<string, unknown>;

/**
 * Acronyms a mechanical kebab/camel split would mangle. Everything else is
 * derived from the name itself, so an unmapped node still reads as words.
 */
const LABEL_TOKENS: Record<string, string> = {
  kd: "K/D",
  kda: "KDA",
  mvp: "MVP",
  otp: "OTP",
  div: "division",
  id: "ID",
};

const OP_KEYS: Record<string, string> = {
  "==": "eq",
  "!=": "ne",
  ">=": "gte",
  ">": "gt",
  "<=": "lte",
  "<": "lt",
  eq: "eq",
  ne: "ne",
  gte: "gte",
  gt: "gt",
  lte: "lte",
  lt: "lt",
};

// ─── Primitives ──────────────────────────────────────────────────────────────

function msg(o: ConditionTextOptions, key: string, values?: Record<string, string | number>): string {
  return o.t(`${NS}.${key}`, values);
}

/** The message when the catalogue has one, otherwise `null`. */
function optional(
  o: ConditionTextOptions,
  key: string,
  values?: Record<string, string | number>
): string | null {
  return o.t.has(`${NS}.${key}`) ? o.t(`${NS}.${key}`, values) : null;
}

/** "hero_kd_best" / "HeroDamageDealt" -> "Hero K/D best" / "Hero damage dealt". */
function humanize(raw: string): string {
  const words = raw
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .split(/[\s_]+/)
    .filter(Boolean)
    .map((word) => LABEL_TOKENS[word.toLowerCase()] ?? word.toLowerCase());
  const sentence = words.join(" ");
  return sentence.charAt(0).toUpperCase() + sentence.slice(1);
}

function text(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(text).join(", ");
  return JSON.stringify(value);
}

function int(value: unknown, fallback: number): number {
  return typeof value === "number" ? value : fallback;
}

/** A 0..1 fraction as a percentage, trailing zeros dropped. */
function percent(value: unknown): string {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return text(value);
  const scaled = n <= 1 ? n * 100 : n;
  return `${Number(scaled.toFixed(2))}%`;
}

/** "at least 5" / "exactly 0" - the operator folded into the value. */
function amount(o: ConditionTextOptions, op: unknown, value: unknown, asPercent = false): string {
  const key = OP_KEYS[text(op) || ">="] ?? "gte";
  return msg(o, `op.${key}`, { value: asPercent ? percent(value) : text(value) });
}

function statName(o: ConditionTextOptions, raw: unknown): string {
  const name = text(raw);
  if (!name) return msg(o, "stat.ImpactRank");
  // The engine also accepts a code ("eliminations"); a one-word code matches its capitalized name, any other is humanized.
  const capitalized = name.charAt(0).toUpperCase() + name.slice(1);
  return optional(o, `stat.${name}`) ?? optional(o, `stat.${capitalized}`) ?? humanize(name);
}

function heroLabel(o: ConditionTextOptions, slug: unknown): string {
  const value = text(slug);
  return o.heroName?.(value) || humanize(value);
}

/** A role param as the rule's game names it; a role that game does not know reads as written, never guessed. */
function roleLabel(o: ConditionTextOptions, raw: unknown): string {
  const value = text(raw);
  return o.roleName?.(value.toLowerCase()) ?? value;
}

/** An enum-ish param value: its message when known, humanized otherwise. */
function word(o: ConditionTextOptions, group: string, value: unknown): string {
  const raw = text(value);
  return optional(o, `${group}.${raw}`) ?? humanize(raw);
}

// ─── Leaf sentences ──────────────────────────────────────────────────────────

/** A leaf's main clause, the parenthesised qualifiers and any sub-conditions. */
interface LeafDraft {
  text: string;
  details?: (string | null)[];
  children?: ConditionSentence[];
}

type Builder = (p: Params, o: ConditionTextOptions) => LeafDraft;

/** Qualifiers that several nodes share, each emitted only when its param is set. */
const scopeDetail = (p: Params, o: ConditionTextOptions): string | null =>
  p.scope === "tournament" ? msg(o, "q.perTournament") : null;

const rankFilters = (p: Params, o: ConditionTextOptions): (string | null)[] => [
  p.role != null ? msg(o, "q.rankRole", { role: roleLabel(o, p.role) }) : null,
  p.platform != null ? msg(o, "q.platform", { platform: text(p.platform) }) : null,
  p.season != null ? msg(o, "q.season", { season: text(p.season) }) : null,
];

const BUILDERS: Record<string, Builder> = {
  // ── Match ──
  stat_threshold: (p, o) => ({
    text: msg(o, "leaf.stat_threshold", { stat: statName(o, p.stat), amount: amount(o, p.op, p.value) }),
  }),
  hero_stat: (p, o) => ({
    text: msg(o, "leaf.hero_stat", {
      stat: statName(o, p.stat),
      hero: heroLabel(o, p.hero_slug),
      amount: amount(o, p.op, p.value),
    }),
  }),
  match_win: (_p, o) => ({ text: msg(o, "leaf.match_win") }),
  match_criteria: (p, o) => ({
    text: msg(o, "leaf.match_criteria", {
      field: word(o, "q.matchField", p.field),
      amount: amount(o, p.op, p.value),
    }),
  }),
  match_mvp_check: (p, o) => ({
    text: msg(o, "leaf.match_mvp_check", {
      top: int(p.top_n, 3),
      stat: statName(o, p.stat ?? "ImpactRank"),
      amount: amount(o, p.op ?? "==", p.value ?? 0),
    }),
    details: [
      p.sort_order === "asc" || p.sort_order === "desc"
        ? msg(o, `q.sortOrder.${p.sort_order}`)
        : null,
    ],
  }),
  match_event_count: (p, o) => ({
    text: msg(o, "leaf.match_event_count", {
      event: word(o, "q.event", p.event),
      amount: amount(o, p.op, p.value),
    }),
    details: [p.hero_slug ? msg(o, "q.onHero", { hero: heroLabel(o, p.hero_slug) }) : null],
  }),
  fight_multikill: (p, o) => ({
    text: msg(o, "leaf.fight_multikill", {
      kills: int(p.min_kills, 3),
      amount: amount(o, p.op ?? ">=", p.value ?? 1),
    }),
  }),

  // ── Hero ──
  hero_kd_best: (p, o) => ({
    text: p.hero_slug
      ? msg(o, "leaf.hero_kd_best", { hero: heroLabel(o, p.hero_slug) })
      : msg(o, "leaf.hero_kd_best_any"),
    details: [
      p.min_time != null ? msg(o, "q.minTimeOnHero", { seconds: text(p.min_time) }) : null,
      p.min_matches != null ? msg(o, "q.minMatchesOnHero", { count: int(p.min_matches, 3) }) : null,
      p.min_match_time != null
        ? msg(o, "q.minMatchTime", { seconds: text(p.min_match_time) })
        : null,
    ],
  }),
  hero_pickrate: (p, o) => ({
    text: msg(o, "leaf.hero_pickrate", { amount: amount(o, p.op ?? "<", p.value ?? 0.001, true) }),
  }),

  // ── Series ──
  encounter_score: (p, o) => ({
    text: msg(o, "leaf.encounter_score", { scores: formatScores(p.scores) }),
    details: [
      p.round_type === "final" ? msg(o, "q.inFinal") : null,
      msg(o, `q.side.${sideOf(p)}`),
    ],
  }),
  encounter_revenge: (_p, o) => ({ text: msg(o, "leaf.encounter_revenge") }),
  encounter_result: (p, o) => ({
    text: msg(o, p.outcome === "loss" ? "leaf.encounter_result_loss" : "leaf.encounter_result_win"),
    details: [
      p.margin != null ? msg(o, "q.margin", { count: int(p.margin, 0) }) : null,
      p.opponent_score != null
        ? msg(o, "q.opponentScore", { count: int(p.opponent_score, 0) })
        : null,
      p.round_type === "final" ? msg(o, "q.inFinal") : null,
    ],
  }),
  encounter_comeback: (p, o) => ({
    text: msg(o, "leaf.encounter_comeback", { count: int(p.min_deficit, 2) }),
  }),

  // ── Bracket and format ──
  bracket_path: (p, o) => ({
    text: msg(o, p.played_upper_bracket === true ? "leaf.bracket_path_upper" : "leaf.bracket_path_lower"),
    details: [
      p.min_lower_bracket_wins != null
        ? msg(o, "q.lowerBracketWins", { count: int(p.min_lower_bracket_wins, 1) })
        : null,
      lostInRound(p, o),
    ],
  }),
  tournament_format: (p, o) => ({
    text: msg(o, "leaf.tournament_format", { format: word(o, "q.format", p.format ?? "double_elim") }),
  }),
  stage_completed: (p, o) => ({
    text: msg(o, "leaf.stage_completed", { amount: amount(o, p.op ?? "==", p.value) }),
  }),
  reached_playoffs: (p, o) =>
    p.scope === "global"
      ? {
          text: msg(o, "leaf.reached_playoffs_count", {
            amount: amount(o, p.op ?? ">=", p.value ?? 1),
          }),
        }
      : { text: msg(o, "leaf.reached_playoffs") },

  // ── Standings ──
  standing_position: (p, o) => ({
    text: msg(o, "leaf.standing_position", { amount: amount(o, p.op, p.value) }),
  }),
  standing_record: (p, o) => ({
    text: msg(o, "leaf.standing_record", {
      field: word(o, "q.record", p.field),
      amount: amount(o, p.op, p.value),
    }),
    details: [
      p.groups_only === true ? msg(o, "q.groupsOnly") : null,
      p.include_groups === true ? msg(o, "q.groupsIncluded") : null,
    ],
  }),
  standing_count: (p, o) => ({
    text: msg(o, p.count_by === "role" ? "leaf.standing_count_role" : "leaf.standing_count", {
      position: amount(o, p.position_op ?? "==", p.position_value ?? 1),
      amount: amount(o, p.op, p.value),
    }),
    details: [leagueDetail(p.is_league, o)],
  }),
  tournament_winrate: (p, o) => ({
    text: msg(o, "leaf.tournament_winrate", { amount: amount(o, p.op, p.value, true) }),
  }),

  // ── Divisions and rank ──
  div_level: (p, o) => ({
    text: msg(o, "leaf.div_level", { amount: amount(o, p.op, p.value) }),
  }),
  div_change: (p, o) => ({
    text: msg(o, p.direction === "down" ? "leaf.div_change_down" : "leaf.div_change_up", {
      count: int(p.min_shift, 1),
    }),
  }),
  div_span: (p, o) => ({
    text: msg(o, "leaf.div_span", { amount: amount(o, p.op, p.value) }),
  }),
  rank_peak: (p, o) => ({
    text: msg(o, "leaf.rank_peak", { division: word(o, "division", p.min_division) }),
    details: rankFilters(p, o),
  }),
  rank_climb: (p, o) => ({
    text: msg(o, "leaf.rank_climb", { amount: amount(o, p.op, p.value) }),
    details: rankFilters(p, o),
  }),
  player_div: (p, o) => ({
    text: msg(o, "leaf.player_div", { amount: amount(o, p.op, p.value) }),
  }),
  player_role: (p, o) => ({
    text: msg(o, "leaf.player_role", { role: roleLabel(o, p.role) }),
  }),

  // ── Participation ──
  is_captain: (_p, o) => ({ text: msg(o, "leaf.is_captain") }),
  is_newcomer: (p, o) =>
    p.op && p.value != null
      ? { text: msg(o, "leaf.is_newcomer_count", { amount: amount(o, p.op, p.value) }) }
      : { text: msg(o, "leaf.is_newcomer") },
  tournament_type: (p, o) => ({
    text: msg(
      o,
      p.is_league === true
        ? "leaf.tournament_type_league"
        : p.is_league === false
          ? "leaf.tournament_type_regular"
          : "leaf.tournament_type_any"
    ),
  }),
  tournament_count: (p, o) => ({
    text: msg(o, "leaf.tournament_count", { amount: amount(o, p.op, p.value) }),
    details: [
      leagueDetail(p.is_league, o),
      p.start_after != null ? msg(o, "q.startedAfter", { date: text(p.start_after) }) : null,
      p.start_before != null ? msg(o, "q.startedBefore", { date: text(p.start_before) }) : null,
    ],
  }),
  draft_pick: (p, o) => {
    if (p.role === "captain") return { text: msg(o, "leaf.draft_pick_captain") };
    const details = [
      p.autopick === true ? msg(o, "q.autopick") : null,
      p.autopick === false ? msg(o, "q.notAutopick") : null,
    ];
    return p.op && p.value != null
      ? { text: msg(o, "leaf.draft_pick", { amount: amount(o, p.op, p.value) }), details }
      : { text: msg(o, "leaf.draft_pick_any"), details };
  },
  registration_timing: (p, o) => ({
    text: msg(o, "leaf.registration_timing", {
      event: word(o, "q.regEvent", p.event),
      amount: amount(o, p.op, p.value),
    }),
    details: [typeof p.value === "number" && p.value < 0 ? msg(o, "q.beforeOpening") : null],
  }),
  registration_flag: (p, o) => ({
    text: word(o, p.value === false ? "q.flagFalse" : "q.flagTrue", p.flag),
  }),
  log_upload_count: (p, o) => ({
    text: msg(o, "leaf.log_upload_count", { amount: amount(o, p.op, p.value) }),
    details: [
      scopeDetail(p, o),
      p.status === "any" ? msg(o, "q.anyStatus") : null,
      p.status != null && p.status !== "any" && p.status !== "done"
        ? msg(o, "q.status", { status: text(p.status) })
        : null,
    ],
  }),
  captain_report_activity: (p, o) => ({
    text: msg(o, "leaf.captain_report_activity", {
      metric: word(o, "q.reportMetric", p.metric),
      amount: amount(o, p.op, p.value),
    }),
  }),

  // ── Team ──
  team_players_match: (p, o) => {
    const mode = text(p.mode);
    const draft: LeafDraft =
      mode === "count"
        ? {
            text: msg(o, "leaf.team_players_match_count", {
              amount: amount(o, p.count_op ?? ">=", p.count_value ?? 1),
            }),
          }
        : { text: msg(o, mode === "any" ? "leaf.team_players_match_any" : "leaf.team_players_match_all") };
    return { ...draft, children: [describeCondition(p.condition as ConditionNode, o)] };
  },
  captain_property: (p, o) => ({
    text: msg(o, "leaf.captain_property"),
    children: [describeCondition(p.condition as ConditionNode, o)],
  }),
  team_otp_count: (p, o) => ({
    text: msg(o, "leaf.team_otp_count", { amount: amount(o, p.op ?? ">=", p.value ?? 1) }),
  }),
  teammate_recurrence: (p, o) => ({
    text: msg(o, "leaf.teammate_recurrence", { amount: amount(o, p.op ?? ">=", p.value ?? 3) }),
  }),

  // ── Career ──
  global_stat_sum: (p, o) => ({
    text: msg(o, "leaf.global_stat_sum", {
      stat: statName(o, p.stat),
      amount: amount(o, p.op, p.value),
    }),
  }),
  global_winrate: (p, o) => {
    const metric = word(o, "q.winrateMetric", p.metric ?? "winrate");
    const limit = p.limit;
    return {
      text:
        limit != null
          ? msg(o, p.order === "asc" ? "leaf.global_winrate_bottom" : "leaf.global_winrate_top", {
              limit: text(limit),
              metric,
            })
          : msg(o, "leaf.global_winrate", { metric }),
      details: [
        p.op && p.value != null
          ? msg(o, "q.winrateThreshold", { amount: amount(o, p.op, p.value, true) })
          : null,
        p.include_league === true ? msg(o, "q.leaguesIncluded") : null,
      ],
    };
  },
  distinct_count: (p, o) => ({
    text: msg(o, "leaf.distinct_count", {
      field: word(o, "q.distinct", p.field),
      amount: amount(o, p.op, p.value),
    }),
    details: [
      scopeDetail(p, o),
      p.min_playtime != null
        ? msg(o, "q.minPlaytimeEach", { seconds: text(p.min_playtime) })
        : null,
    ],
  }),
  map_coverage: (p, o) => ({
    text: msg(o, p.outcome === "won" ? "leaf.map_coverage_won" : "leaf.map_coverage_played", {
      field: word(o, "q.coverage", p.field),
      amount: amount(o, p.op, p.value),
    }),
    details: [
      p.gamemode != null ? msg(o, "q.gamemode", { name: text(p.gamemode) }) : null,
      scopeDetail(p, o),
    ],
  }),
  map_winrate: (p, o) => ({
    text: p.map_name
      ? msg(o, "leaf.map_winrate_map", { map: text(p.map_name), amount: amount(o, p.op, p.value, true) })
      : msg(o, "leaf.map_winrate", { amount: amount(o, p.op, p.value, true) }),
    details: [
      p.min_matches != null ? msg(o, "q.minMapMatches", { count: int(p.min_matches, 5) }) : null,
    ],
  }),
  log_stat_rank: (p, o) => ({
    text: msg(o, p.order === "asc" ? "leaf.log_stat_rank_bottom" : "leaf.log_stat_rank_top", {
      limit: text(p.limit ?? 1),
      stat: statName(o, p.stat),
    }),
    details: [p.normalize_by_time === true ? msg(o, "q.perTimePlayed") : null],
  }),
  duel_dominance: (p, o) => ({
    text: msg(o, "leaf.duel_dominance", { amount: amount(o, p.op ?? ">=", p.value ?? 1) }),
    details: [
      msg(o, "q.minKillsEach", { count: int(p.min_kills, 10) }),
      p.min_diff != null ? msg(o, "q.minDiff", { count: int(p.min_diff, 1) }) : null,
      scopeDetail(p, o),
    ],
  }),
  consecutive: (p, o) => ({
    text: msg(o, "leaf.consecutive", {
      metric: word(o, "q.streakMetric", p.metric),
      count: int(p.min_streak, 2),
    }),
    details: [
      p.metric === "day_two"
        ? msg(o, "q.dayTwoPosition", {
            amount: amount(o, p.position_op ?? "<", p.position_value ?? 7),
          })
        : null,
    ],
  }),
  stable_streak: (p, o) => ({
    text: msg(o, "leaf.stable_streak", {
      fields: (Array.isArray(p.fields) ? p.fields : [])
        .map((field) => word(o, "q.stableField", field))
        .join(", "),
      count: int(p.min_streak, 2),
    }),
  }),
};

/** "3:0 or 3:1" - the scoreline pairs the engine matches on. */
function formatScores(scores: unknown): string {
  if (!Array.isArray(scores)) return text(scores);
  return scores
    .map((pair) => (Array.isArray(pair) ? pair.map(text).join(":") : text(pair)))
    .join(" / ");
}

/** `side` wins over the legacy `winner` boolean, exactly as the engine reads it. */
function sideOf(p: Params): string {
  if (typeof p.side === "string") return p.side;
  return p.winner === false ? "both" : "winner";
}

function lostInRound(p: Params, o: ConditionTextOptions): string | null {
  const round = p.lost_in_round as { op?: string; value?: unknown } | undefined;
  if (!round?.op) return null;
  return msg(o, "q.lostInRound", { amount: amount(o, round.op, round.value) });
}

function leagueDetail(isLeague: unknown, o: ConditionTextOptions): string | null {
  if (isLeague === true) return msg(o, "q.leaguesOnly");
  if (isLeague === null) return msg(o, "q.leaguesIncluded");
  return null;
}

/** Any node, named: the catalogue label, or the node name read as words. */
function conditionTypeLabel(type: string | undefined, o: ConditionTextOptions): string {
  if (!type) return msg(o, "unnamed");
  const key = `achievements.condition.${type}`;
  return o.t.has(key) ? o.t(key) : humanize(type);
}

/** A node with no message of its own: its label plus its params, spelled out. */
function fallbackLeaf(type: string, params: Params, o: ConditionTextOptions): LeafDraft {
  const pairs = Object.entries(params)
    .filter(([, value]) => value !== null && value !== undefined)
    .map(([key, value]) => `${humanize(key)} ${text(value)}`);
  const label = conditionTypeLabel(type, o);
  return pairs.length > 0 ? { text: `${label}: ${pairs.join(", ")}` } : { text: label };
}

export function describeLeaf(
  type: string,
  params: Params,
  o: ConditionTextOptions
): ConditionSentence {
  const build = BUILDERS[type];
  const draft = build ? build(params, o) : fallbackLeaf(type, params, o);
  const details = (draft.details ?? []).filter((detail): detail is string => !!detail);
  const sentence = details.length > 0 ? `${draft.text} (${details.join(", ")})` : draft.text;
  return draft.children ? { text: sentence, children: draft.children } : { text: sentence };
}

export function describeCondition(
  node: ConditionNode | null | undefined,
  o: ConditionTextOptions
): ConditionSentence {
  if (!node || typeof node !== "object") return { text: o.t("achievements.emptyCondition") };
  if ("AND" in node) {
    return {
      group: "AND",
      text: msg(o, "group.and"),
      children: node.AND.map((child) => describeCondition(child, o)),
    };
  }
  if ("OR" in node) {
    return {
      group: "OR",
      text: msg(o, "group.or"),
      children: node.OR.map((child) => describeCondition(child, o)),
    };
  }
  if ("NOT" in node) {
    return { group: "NOT", text: msg(o, "group.not"), children: [describeCondition(node.NOT, o)] };
  }
  if ("type" in node && node.type) {
    return describeLeaf(node.type, node.params ?? {}, o);
  }
  return { text: o.t("achievements.emptyCondition") };
}

/** The same sentence on one line - for a canvas node or the outline. */
export function sentenceToLine(sentence: ConditionSentence): string {
  if (!sentence.children?.length) return sentence.text;
  return `${sentence.text} ${sentence.children.map(sentenceToLine).join("; ")}`;
}

// ─── Hook ────────────────────────────────────────────────────────────────────

/** Whether the tree sets `param` anywhere, so a catalogue or ontology is only read for trees that name one. */
function mentions(node: unknown, param: string): boolean {
  if (Array.isArray(node)) return node.some((child) => mentions(child, param));
  if (!node || typeof node !== "object") return false;
  return Object.entries(node).some(
    ([key, value]) => (key === param && typeof value === "string") || mentions(value, param)
  );
}

/**
 * The describer bound to the current locale and to the rule's own game: its character catalogue (hero names) and
 * its role ontology (role names, localized like every role label) read on the caller's resolved workspace `axis`
 * — the viewing workspace (a tenant host's own), the rule's workspace in the editor — so a workspace's child roles
 * resolve; the metadata key carries that axis.
 *
 * `tree` is only used to decide whether the catalogue / ontology is worth fetching;
 * the returned functions work on any node.
 */
export function useConditionText(tree: unknown, discipline: string, axis: WorkspaceAxis) {
  const translate = useTranslations();
  const t = translate as unknown as ConditionTranslator;
  const nameOfRole = useRoleName();

  const needsHeroes = useMemo(() => mentions(tree, "hero_slug"), [tree]);
  const { data: heroes } = useCatalogEntities(discipline, "character", { enabled: needsHeroes });
  const needsRoles = useMemo(() => mentions(tree, "role"), [tree]);
  const { data: ontology } = useDisciplineMetadata(axis, needsRoles ? discipline : null);

  const heroName = useCallback(
    (slug: string) => heroes?.find((hero) => hero.slug === slug)?.name ?? humanize(slug),
    [heroes]
  );
  const roleName = useCallback(
    (code: string) => {
      const rated = ontology ? ratedDimension(ontology) : null;
      const role = ontology && rated ? findRole(ontology, { dimension: rated.code, role: code }) : null;
      return role ? nameOfRole(role) : null;
    },
    [ontology, nameOfRole]
  );

  return useMemo(() => {
    const options: ConditionTextOptions = { t, heroName, roleName };
    return {
      describe: (node: ConditionNode | null | undefined) => describeCondition(node, options),
      leafLabel: (type: string | undefined) => conditionTypeLabel(type, options),
      leafLine: (type: string, params: Params) =>
        sentenceToLine(describeLeaf(type, params, options)),
    };
  }, [t, heroName, roleName]);
}
