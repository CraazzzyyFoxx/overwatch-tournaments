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
  "HeroTimePlayed", "UltimatesEarned", "ImpactRank", "KD", "KDA",
] as const;
export type AchievementStat = (typeof STATS)[number];
export const STAT_LABEL_KEYS: Record<AchievementStat, `stats.${AchievementStat}`> = Object.fromEntries(
  STATS.map((stat) => [stat, `stats.${stat}`]),
) as Record<AchievementStat, `stats.${AchievementStat}`>;

// ─── Palette ─────────────────────────────────────────────────────────────────

export function createSidebarGroups(t: (key: string) => string): RulePaletteGroup[] {
  return [
  {
    label: t("logic"),
    items: [
      { type: "logical", logicalOp: "AND", label: t("logicalAnd"), color: LOGICAL_COLORS.AND },
      { type: "logical", logicalOp: "OR", label: t("logicalOr"), color: LOGICAL_COLORS.OR },
      { type: "logical", logicalOp: "NOT", label: t("logicalNot"), color: LOGICAL_COLORS.NOT },
    ],
  },
  {
    label: t("match"),
    items: [
      { type: "leaf", leafType: "stat_threshold", label: t("statThreshold") },
      { type: "leaf", leafType: "match_criteria", label: t("matchCriteria") },
      { type: "leaf", leafType: "match_win", label: t("matchWin") },
      { type: "leaf", leafType: "hero_stat", label: t("heroStat") },
      { type: "leaf", leafType: "match_mvp_check", label: t("mvpCheck") },
    ],
  },
  {
    label: t("tournament"),
    items: [
      { type: "leaf", leafType: "standing_position", label: t("position") },
      { type: "leaf", leafType: "standing_record", label: t("record") },
      { type: "leaf", leafType: "div_change", label: t("divisionChange") },
      { type: "leaf", leafType: "div_level", label: t("divisionLevel") },
      { type: "leaf", leafType: "is_captain", label: t("isCaptain") },
      { type: "leaf", leafType: "is_newcomer", label: t("isNewcomer") },
      { type: "leaf", leafType: "tournament_type", label: t("tournamentType") },
      { type: "leaf", leafType: "hero_kd_best", label: t("heroKdBest") },
      { type: "leaf", leafType: "team_players_match", label: t("teamPlayers") },
      { type: "leaf", leafType: "captain_property", label: t("captainProperty") },
      { type: "leaf", leafType: "encounter_score", label: t("encounterScore") },
      { type: "leaf", leafType: "encounter_revenge", label: t("encounterRevenge") },
      { type: "leaf", leafType: "bracket_path", label: t("bracketPath") },
      { type: "leaf", leafType: "tournament_format", label: t("format") },
      { type: "leaf", leafType: "stage_completed", label: t("stageCompleted") },
    ],
  },
  {
    label: t("global"),
    items: [
      { type: "leaf", leafType: "global_stat_sum", label: t("globalStatSum") },
      { type: "leaf", leafType: "tournament_count", label: t("tournamentCount") },
      { type: "leaf", leafType: "global_winrate", label: t("globalWinrate") },
      { type: "leaf", leafType: "distinct_count", label: t("distinctCount") },
      { type: "leaf", leafType: "consecutive", label: t("consecutive") },
      { type: "leaf", leafType: "stable_streak", label: t("stableStreak") },
    ],
  },
  ];
}

/**
 * The palette a game's engine registry actually offers. `offered` is the set of
 * leaf types the registry returned for the editor's discipline: a static palette
 * entry the registry does not know is dropped (an Overwatch node is not a League
 * node), a group left without nodes disappears, and a registry node the static
 * palette has no entry for lands in a trailing group so the palette never offers
 * fewer nodes than the leaf selector. The logical operators stay: every tree needs them.
 */
export function filterPaletteByConditions(
  groups: RulePaletteGroup[],
  offered: ReadonlySet<string>,
  other: { label: string; labelFor: (leafType: string) => string }
): RulePaletteGroup[] {
  const known = new Set<string>();
  const filtered = groups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => {
        if (item.type !== "leaf") return true;
        known.add(item.leafType ?? "");
        return offered.has(item.leafType ?? "");
      }),
    }))
    .filter((group) => group.items.length > 0);
  const unlisted = [...offered].filter((leafType) => !known.has(leafType));
  if (unlisted.length === 0) return filtered;
  return [
    ...filtered,
    {
      label: other.label,
      items: unlisted.map((leafType) => ({ type: "leaf" as const, leafType, label: other.labelFor(leafType) })),
    },
  ];
}

/**
 * The leaf a new node starts as, drawn from what the registry offers: the usual
 * `preferred` one when the game has it, otherwise the first the game offers.
 * `null` when the game offers none — there is then nothing to add, and no
 * stand-in from another game.
 */
export function defaultLeafOf(offered: readonly string[], preferred: string): string | null {
  return offered.includes(preferred) ? preferred : (offered[0] ?? null);
}
