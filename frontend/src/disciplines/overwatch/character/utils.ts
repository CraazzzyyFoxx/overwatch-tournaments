import type { Formatter } from "@/lib/datetime";

import { LogStatsName } from "../stat-names";
import type { CharacterSummary } from "@/types/user.types";

/** Only `number` is needed here; `useFormatter()` and `await getFormatter()` both satisfy it. */
export type NumberFormatter = Pick<Formatter, "number">;

const STAT_NUMBER_OPTIONS = { maximumFractionDigits: 2 } as const;
const ACCURACY_OPTIONS = { style: "percent", maximumFractionDigits: 1 } as const;

export const formatStatValue = (format: NumberFormatter, name: string, value: number) => {
  if (!Number.isFinite(value)) {
    return "-";
  }

  if (name.includes("accuracy")) {
    if (value > 1) return "-";
    return format.number(value, ACCURACY_OPTIONS);
  }

  if (Math.abs(value) >= 1000) {
    return format.number(Math.round(value), STAT_NUMBER_OPTIONS);
  }
  return format.number(value, STAT_NUMBER_OPTIONS);
};

/** Lower is better: the backend's `asc` stats (`LOG_STATS_DEFAULT_DIRECTION`, `shared/core/enums.py`). */
const LOWER_IS_BETTER = new Set<string>([
  LogStatsName.Deaths,
  LogStatsName.DamageTaken,
  LogStatsName.EnvironmentalDeaths,
  LogStatsName.ShotsMissed,
  LogStatsName.DamageFB,
  LogStatsName.Performance,
  LogStatsName.FirstDeaths,
  LogStatsName.ImpactRank
]);

export const isRevertedStat = (name: string) => LOWER_IS_BETTER.has(name);

export const computeDelta = (userAvg: number, globalAvg: number, reversed: boolean) => {
  if (!Number.isFinite(userAvg) || !Number.isFinite(globalAvg) || globalAvg <= 0) {
    return null;
  }
  const raw = reversed ? (globalAvg - userAvg) / globalAvg : (userAvg - globalAvg) / globalAvg;
  if (!Number.isFinite(raw)) return null;
  return raw;
};

export const formatDelta = (delta: number) => {
  const sign = delta > 0 ? "+" : "";
  return `${sign}${(delta * 100).toFixed(0)}%`;
};

/** A delta's quality colour: emerald when better, rose when worse, faint when there is none. */
export const deltaColor = (delta: number | null) => {
  if (delta == null) return "var(--aqt-fg-faint)";
  if (delta > 0) return "var(--aqt-emerald)";
  return delta < 0 ? "var(--aqt-rose)" : "var(--aqt-fg-muted)";
};

export const getOverall = (row: CharacterSummary, name: LogStatsName) => {
  return row.stats.find((s) => s.name === name)?.overall ?? 0;
};

// Winrate can arrive as a 0..1 fraction or an already-scaled percent; normalize
// to a fraction the same way the Heroes tab does.
export const toFraction = (value: number | null | undefined): number | null => {
  if (value == null || !Number.isFinite(value)) return null;
  return value <= 1 ? value : value / 100;
};


export const statAvg10 = (stats: CharacterSummary["stats"], name: LogStatsName): number | null => {
  const stat = stats.find((s) => s.name === name);
  return stat && Number.isFinite(stat.avg_10) ? stat.avg_10 : null;
};

/** The player's winrate (0..1) on a hero from its game record; `null` without a game. */
export const heroWinrate = (hero: Pick<CharacterSummary, "games" | "win">): number | null =>
  hero.games > 0 ? hero.win / hero.games : null;
