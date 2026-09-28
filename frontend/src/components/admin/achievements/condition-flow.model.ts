/**
 * The achievement engine's half of the condition builder: leaf labels, the
 * one-line parameter summary and the palette.
 *
 * The tree ↔ flow-graph conversion, layout and canvas live in
 * `@/components/rule-builder`, which the pick-ban constructor shares. This file
 * is the registry that turns that generic canvas into the achievement editor.
 *
 * Pure: no React, so it stays out of the editor's lazily loaded chunk boundary
 * and can be unit-tested without a canvas.
 */
import { LOGICAL_COLORS, type RulePaletteGroup } from "@/components/rule-builder";

// ─── Constants ───────────────────────────────────────────────────────────────

export const OPERATORS = ["==", "!=", ">=", ">", "<=", "<"];
export const STATS = [
  "Eliminations", "FinalBlows", "Deaths", "AllDamageDealt", "HeroDamageDealt",
  "HealingDealt", "DamageTaken", "DamageBlocked", "EnvironmentalKills",
  "EnvironmentalDeaths", "ScopedCriticalHitKills", "SoloKills", "CriticalHits",
  "HeroTimePlayed", "UltimatesEarned", "Performance", "KD", "KDA",
];

/** The leaf a node with no type falls back to — the engine's "this match" predicate. */
export const DEFAULT_CONDITION_TYPE = "match_win";

/**
 * Acronyms and shorthands a mechanical kebab→Title would mangle. Everything
 * else derives from the node name itself, so a node added on the backend shows
 * up here without an edit.
 */
const LABEL_TOKENS: Record<string, string> = {
  kd: "K/D",
  mvp: "MVP",
  otp: "OTP",
  div: "division",
};

// ─── Labels ──────────────────────────────────────────────────────────────────

export function conditionLabel(name: string | undefined): string {
  if (!name) return "condition";
  const words = name.split("_").map((word) => LABEL_TOKENS[word] ?? word);
  const sentence = words.join(" ");
  return sentence.charAt(0).toUpperCase() + sentence.slice(1);
}

export function formatParamsSummary(type: string, params: Record<string, unknown>): string {
  const parts: string[] = [];
  if (params.stat) parts.push(String(params.stat));
  if (params.field && type !== "distinct_count") parts.push(String(params.field));
  if (params.op) parts.push(`${params.op} ${params.value ?? ""}`);
  if (params.direction) parts.push(`${params.direction} >= ${params.min_shift}`);
  if (params.hero_slug) parts.push(`hero: ${params.hero_slug}`);
  if (params.metric) parts.push(`${params.metric}, streak >= ${params.min_streak}`);
  if (params.order) parts.push(`${params.order} ${params.limit ?? ""}`);
  if (type === "match_mvp_check") {
    parts.push(`${params.stat ?? "Performance"} top ${params.top_n ?? 3}, team in top ${params.op ?? "=="} ${params.value ?? 0}`);
  }
  if (type === "tournament_format") {
    const fmtLabels: Record<string, string> = { double_elim: "Double elim", single_elim: "Single elim", round_robin: "Round robin", has_bracket: "Any bracket" };
    parts.push(fmtLabels[(params.format as string) ?? "double_elim"] ?? String(params.format));
  }
  if (type === "bracket_path") {
    const path = params.played_upper_bracket === true ? "upper only" : "lower bracket";
    const lb = params.min_lower_bracket_wins ? `, LB wins >= ${params.min_lower_bracket_wins}` : "";
    const lr = (params.lost_in_round as { op?: string; value?: number })?.op
      ? `, lost round ${(params.lost_in_round as { op?: string }).op} ${(params.lost_in_round as { value?: number }).value}`
      : "";
    parts.push(`${path}${lb}${lr}`);
  }
  if (type === "tournament_type") {
    parts.push(params.is_league === null || params.is_league === undefined ? "any" : `league: ${params.is_league}`);
  }
  if (type === "is_newcomer" && params.op) {
    parts.push(`newcomer count ${params.op} ${params.value}`);
  }
  if (params.field && type === "distinct_count") parts.push(`${params.field} ${params.op} ${params.value}`);
  if (type === "player_role") parts.push(`role: ${params.role ?? ""}`);
  if (type === "player_div") parts.push(`div ${params.op ?? "=="} ${params.value ?? ""}`);
  if (params.fields && type === "stable_streak") {
    const fields = params.fields as string[];
    parts.push(`[${fields.join(", ")}] streak >= ${params.min_streak ?? 2}`);
  }
  return parts.join(", ");
}

// ─── Palette ─────────────────────────────────────────────────────────────────

export const SIDEBAR_GROUPS: RulePaletteGroup[] = [
  {
    label: "Logic",
    items: [
      { type: "logical", logicalOp: "AND", label: "AND", color: LOGICAL_COLORS.AND },
      { type: "logical", logicalOp: "OR", label: "OR", color: LOGICAL_COLORS.OR },
      { type: "logical", logicalOp: "NOT", label: "NOT", color: LOGICAL_COLORS.NOT },
    ],
  },
  {
    label: "Match",
    items: [
      { type: "leaf", leafType: "stat_threshold", label: "Stat threshold" },
      { type: "leaf", leafType: "match_criteria", label: "Match criteria" },
      { type: "leaf", leafType: "match_win", label: "Match win" },
      { type: "leaf", leafType: "hero_stat", label: "Hero stat" },
      { type: "leaf", leafType: "match_mvp_check", label: "MVP check" },
    ],
  },
  {
    label: "Tournament",
    items: [
      { type: "leaf", leafType: "standing_position", label: "Position" },
      { type: "leaf", leafType: "standing_record", label: "Record" },
      { type: "leaf", leafType: "div_change", label: "Division change" },
      { type: "leaf", leafType: "div_level", label: "Division level" },
      { type: "leaf", leafType: "is_captain", label: "Is captain" },
      { type: "leaf", leafType: "is_newcomer", label: "Is newcomer" },
      { type: "leaf", leafType: "tournament_type", label: "Tournament type" },
      { type: "leaf", leafType: "hero_kd_best", label: "Hero K/D best" },
      { type: "leaf", leafType: "team_players_match", label: "Team players" },
      { type: "leaf", leafType: "captain_property", label: "Captain property" },
      { type: "leaf", leafType: "encounter_score", label: "Encounter score" },
      { type: "leaf", leafType: "encounter_revenge", label: "Encounter revenge" },
      { type: "leaf", leafType: "bracket_path", label: "Bracket path" },
      { type: "leaf", leafType: "tournament_format", label: "Format" },
    ],
  },
  {
    label: "Global",
    items: [
      { type: "leaf", leafType: "global_stat_sum", label: "Global stat sum" },
      { type: "leaf", leafType: "tournament_count", label: "Tournament count" },
      { type: "leaf", leafType: "global_winrate", label: "Global winrate" },
      { type: "leaf", leafType: "distinct_count", label: "Distinct count" },
      { type: "leaf", leafType: "consecutive", label: "Consecutive" },
      { type: "leaf", leafType: "stable_streak", label: "Stable streak" },
    ],
  },
];
