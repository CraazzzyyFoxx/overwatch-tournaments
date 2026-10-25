import { LOW_SAMPLE_GAMES } from "@/lib/colors";
import type { CatalogEntityRead } from "@/types/catalog.types";
import type { CharacterStatBest, CharacterWithUserStats, UserMapRead } from "@/types/user.types";

import { STAT_META, type StatGroup } from "../match/stats";
import { LogStatsName } from "../stat-names";
import { computeDelta, isRevertedStat } from "./utils";

/** The heroes tab's stat groups in reading order: the match catalogue's own groups. */
export const STAT_GROUPS: readonly StatGroup[] = ["combat", "damage", "tanking", "healing", "utility", "accuracy"];

/** Per class, the per-10 figures it is judged by, its headline first. */
export const CLASS_STATS: Record<string, LogStatsName[]> = {
  tank: [LogStatsName.DamageBlocked, LogStatsName.HeroDamageDealt, LogStatsName.KDA],
  damage: [LogStatsName.HeroDamageDealt, LogStatsName.FinalBlows, LogStatsName.KDA],
  support: [LogStatsName.HealingDealt, LogStatsName.HeroDamageDealt, LogStatsName.KDA]
};

/** Stats a hero carries that the match catalogue does not list. */
const EXTRA_META: Partial<Record<string, { group: StatGroup; labelKey: string }>> = {
  [LogStatsName.FBE]: { group: "combat", labelKey: "matches.stat.fbe" },
  [LogStatsName.ScopedShotsFired]: { group: "accuracy", labelKey: "matches.stat.scopedShotsFired" },
  [LogStatsName.ScopedShotsHit]: { group: "accuracy", labelKey: "matches.stat.scopedShotsHit" }
};

/** The catalogue's order, the extras last in their group. */
const ORDER = [...Object.keys(STAT_META), ...Object.keys(EXTRA_META)];

/** Shares of a match (0..1): a single game tops out at 1 on a handful of shots, so their best is no record. */
const SHARES = new Set<string>([
  LogStatsName.FBE,
  LogStatsName.WeaponAccuracy,
  LogStatsName.CriticalHitAccuracy,
  LogStatsName.ScopedAccuracy,
  LogStatsName.ScopedCriticalHitAccuracy
]);

/** Read once per match (a ratio, a share, a match's maximum): a career sum of them means nothing. */
const PER_MATCH = new Set<string>([...SHARES, LogStatsName.KD, LogStatsName.KDA, LogStatsName.DamageFB, LogStatsName.MultikillBest]);

/** The overview's figures; a hero shows the ones it has data for, so a damage hero lists no healing. */
const OVERVIEW = new Set<string>([
  LogStatsName.Eliminations,
  LogStatsName.FinalBlows,
  LogStatsName.Deaths,
  LogStatsName.SoloKills,
  LogStatsName.ObjectiveKills,
  LogStatsName.HeroDamageDealt,
  LogStatsName.DamageDelta,
  LogStatsName.DamageBlocked,
  LogStatsName.DamageTaken,
  LogStatsName.SelfHealing,
  LogStatsName.HealingDealt,
  LogStatsName.UltimatesEarned,
  LogStatsName.UltimateKills,
  LogStatsName.WeaponAccuracy,
  LogStatsName.CriticalHitAccuracy
]);

/** The single-game records the records card lists, the hero's class headline first. */
const RECORD_STATS: LogStatsName[] = [
  LogStatsName.HeroDamageDealt,
  LogStatsName.HealingDealt,
  LogStatsName.DamageBlocked,
  LogStatsName.Eliminations,
  LogStatsName.FinalBlows,
  LogStatsName.SoloKills
];

export interface StatRow {
  name: LogStatsName;
  group: StatGroup;
  labelKey: string;
  /** The player's figure per 10 minutes (per match for a ratio). */
  value: number;
  /** Every player's figure on the hero; `null` when there is none. */
  average: number | null;
  /** Gain over the average, positive when better whichever way the stat runs; `null` on a low sample. */
  delta: number | null;
  /** Career sum; `null` for a stat read once per match. */
  total: number | null;
  /** The player's best game; `null` where a best is no record (lower is better, or nothing done). */
  best: CharacterStatBest | null;
  /** Every player's best game on the hero, on the same rule. */
  record: CharacterStatBest | null;
  /** The player's best is the hero's record. */
  holdsRecord: boolean;
}

export interface StatSection {
  group: StatGroup;
  rows: StatRow[];
}

const finite = (value: number | null | undefined): value is number => value != null && Number.isFinite(value);

/**
 * A best game that is a record. The best of a lower-is-better stat is a zero from a hero picked for a minute (no
 * deaths, no damage taken) and the best of a share is a 100% from a few shots, so neither is one; nor is a best of
 * nothing done.
 */
const asRecord = (name: string, game: CharacterStatBest | null | undefined): CharacterStatBest | null =>
  game && !isRevertedStat(name) && !SHARES.has(name) && finite(game.value) && game.value > 0 ? game : null;

/** Every stat a hero has data for, in catalogue order. Time played is the hero's header, not a row. */
export function statRows(hero: CharacterWithUserStats): StatRow[] {
  const lowSample = hero.games < LOW_SAMPLE_GAMES;
  const rows: StatRow[] = [];
  for (const stat of hero.stats) {
    const meta = STAT_META[stat.name] ?? EXTRA_META[stat.name];
    if (!meta || stat.name === LogStatsName.HeroTimePlayed || !finite(stat.avg_10)) continue;
    const average = finite(stat.avg_10_all) && stat.avg_10_all > 0 ? stat.avg_10_all : null;
    // Nobody has it: the hero cannot do it (healing on a damage hero), or the logs never count it (assists).
    if (stat.overall === 0 && stat.avg_10 === 0 && average === null) continue;
    const best = asRecord(stat.name, stat.best);
    const record = asRecord(stat.name, stat.best_all);
    rows.push({
      name: stat.name as LogStatsName,
      group: meta.group,
      labelKey: meta.labelKey,
      value: stat.avg_10,
      average,
      delta: lowSample || average === null ? null : computeDelta(stat.avg_10, average, isRevertedStat(stat.name)),
      total: PER_MATCH.has(stat.name) || !finite(stat.overall) ? null : stat.overall,
      best,
      record,
      holdsRecord: best !== null && record !== null && best.value >= record.value
    });
  }
  return rows.sort((a, b) => ORDER.indexOf(a.name) - ORDER.indexOf(b.name));
}

/** Rows bucketed by group, empty groups dropped. */
export function sections(rows: StatRow[]): StatSection[] {
  return STAT_GROUPS.map((group) => ({ group, rows: rows.filter((row) => row.group === group) })).filter(
    (section) => section.rows.length > 0
  );
}

/** The overview's rows: each group's headline figures. */
export const overviewRows = (rows: StatRow[]): StatRow[] => rows.filter((row) => OVERVIEW.has(row.name));

/** The records card's rows: the class headline first, then the rest of the record stats that have a record. */
export function recordRows(rows: StatRow[], heroClass: string | null | undefined): StatRow[] {
  const headline = CLASS_STATS[heroClass ?? ""]?.[0];
  const order = headline ? [headline, ...RECORD_STATS.filter((name) => name !== headline)] : RECORD_STATS;
  return order.flatMap((name) => rows.filter((row) => row.name === name && row.best !== null));
}

export interface HeroMapRow {
  map: CatalogEntityRead;
  games: number;
  win: number;
  loss: number;
  draw: number;
  /** 0..1 */
  winRate: number;
}

/** The maps a hero was played on, most played first: a 1–0 is no headline. */
export function heroMapRows(maps: UserMapRead[], heroId: number): HeroMapRow[] {
  return maps
    .flatMap((row) => {
      const stats = row.character_stats?.find((entry) => entry.character.id === heroId);
      return stats
        ? [{ map: row.map, games: stats.games, win: stats.win, loss: stats.loss, draw: stats.draw, winRate: stats.win_rate }]
        : [];
    })
    .sort((a, b) => b.games - a.games || b.winRate - a.winRate || a.map.name.localeCompare(b.map.name));
}
