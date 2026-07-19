import { LogStatsName } from "@/types/stats.types";
import type { PlayerWithStats, TeamWithStats } from "@/types/team.types";

/**
 * Single source of truth for the match-statistics surface.
 *
 * The match API (`/api/v1/matches/{id}`) returns a *passthrough* dict of every
 * stat name stored for a player/round (the backend query filters only on
 * `hero_id IS NULL`, not on stat name), so ~40 stats are already on the client.
 * The tables/charts historically rendered ~20 of them — this module drives the
 * expanded views (column presets, team comparison, leader cards, contribution
 * chart) from one declarative catalogue so formatting/labels stay consistent.
 */

export type StatFormat = "int" | "float" | "thousands" | "percent" | "duration";

export type StatGroup = "combat" | "damage" | "tanking" | "healing" | "utility" | "accuracy";

export interface StatMeta {
  name: LogStatsName;
  /** Compact column header — OW-standard shorthand, language-neutral. */
  abbr: string;
  /** i18n key for the full human name (tooltips, comparison, leaders). */
  labelKey: string;
  format: StatFormat;
  group: StatGroup;
  /** Lower is better (deaths, damage taken, misses …). */
  reverted?: boolean;
  /** Eligible for an inline magnitude micro-bar in the table. */
  bar?: boolean;
}

const META: StatMeta[] = [
  // ── Combat ──────────────────────────────────────────────────────────────
  { name: LogStatsName.Eliminations, abbr: "E", labelKey: "matches.stat.eliminations", format: "int", group: "combat" },
  { name: LogStatsName.FinalBlows, abbr: "FB", labelKey: "matches.stat.finalBlows", format: "int", group: "combat" },
  { name: LogStatsName.Deaths, abbr: "D", labelKey: "matches.stat.deaths", format: "int", group: "combat", reverted: true },
  { name: LogStatsName.Assists, abbr: "A", labelKey: "matches.stat.assists", format: "int", group: "combat" },
  { name: LogStatsName.KD, abbr: "K/D", labelKey: "matches.stat.kd", format: "float", group: "combat" },
  { name: LogStatsName.KDA, abbr: "KA/D", labelKey: "matches.stat.kda", format: "float", group: "combat" },
  { name: LogStatsName.SoloKills, abbr: "SK", labelKey: "matches.stat.soloKills", format: "int", group: "combat" },
  { name: LogStatsName.ObjectiveKills, abbr: "OK", labelKey: "matches.stat.objectiveKills", format: "int", group: "combat" },
  { name: LogStatsName.Multikills, abbr: "MULTI", labelKey: "matches.stat.multikills", format: "int", group: "combat" },
  { name: LogStatsName.MultikillBest, abbr: "BEST MK", labelKey: "matches.stat.multikillBest", format: "int", group: "combat" },
  { name: LogStatsName.EnvironmentalKills, abbr: "ENV K", labelKey: "matches.stat.environmentalKills", format: "int", group: "combat" },
  { name: LogStatsName.EnvironmentalDeaths, abbr: "ENV D", labelKey: "matches.stat.environmentalDeaths", format: "int", group: "combat", reverted: true },
  { name: LogStatsName.FirstPicks, abbr: "FP", labelKey: "matches.stat.firstPicks", format: "int", group: "combat" },
  { name: LogStatsName.FirstDeaths, abbr: "FD", labelKey: "matches.stat.firstDeaths", format: "int", group: "combat", reverted: true },
  { name: LogStatsName.UltimateKills, abbr: "ULT K", labelKey: "matches.stat.ultimateKills", format: "int", group: "combat" },
  { name: LogStatsName.SupportKills, abbr: "SUP K", labelKey: "matches.stat.supportKills", format: "int", group: "combat" },

  // ── Damage ──────────────────────────────────────────────────────────────
  { name: LogStatsName.HeroDamageDealt, abbr: "DMG", labelKey: "matches.stat.heroDamageDealt", format: "thousands", group: "damage", bar: true },
  { name: LogStatsName.AllDamageDealt, abbr: "ALL DMG", labelKey: "matches.stat.allDamageDealt", format: "thousands", group: "damage", bar: true },
  { name: LogStatsName.BarrierDamageDealt, abbr: "BAR DMG", labelKey: "matches.stat.barrierDamageDealt", format: "thousands", group: "damage", bar: true },
  { name: LogStatsName.DamageFB, abbr: "DMG/FB", labelKey: "matches.stat.damageFb", format: "thousands", group: "damage" },
  { name: LogStatsName.DamageDelta, abbr: "Δ DMG", labelKey: "matches.stat.damageDelta", format: "thousands", group: "damage" },

  // ── Tanking / mitigation ────────────────────────────────────────────────
  { name: LogStatsName.DamageTaken, abbr: "DMG TKN", labelKey: "matches.stat.damageTaken", format: "thousands", group: "tanking", bar: true, reverted: true },
  { name: LogStatsName.DamageBlocked, abbr: "BLK", labelKey: "matches.stat.damageBlocked", format: "thousands", group: "tanking", bar: true },
  { name: LogStatsName.SelfHealing, abbr: "SELF HL", labelKey: "matches.stat.selfHealing", format: "thousands", group: "tanking", bar: true },

  // ── Healing / support ───────────────────────────────────────────────────
  { name: LogStatsName.HealingDealt, abbr: "HEAL", labelKey: "matches.stat.healingDealt", format: "thousands", group: "healing", bar: true },
  { name: LogStatsName.HealingReceived, abbr: "HEAL RCV", labelKey: "matches.stat.healingReceived", format: "thousands", group: "healing", bar: true },
  { name: LogStatsName.DefensiveAssists, abbr: "DEF A", labelKey: "matches.stat.defensiveAssists", format: "int", group: "healing" },
  { name: LogStatsName.OffensiveAssists, abbr: "OFF A", labelKey: "matches.stat.offensiveAssists", format: "int", group: "healing" },

  // ── Utility ─────────────────────────────────────────────────────────────
  { name: LogStatsName.UltimatesEarned, abbr: "ULT ⚡", labelKey: "matches.stat.ultimatesEarned", format: "int", group: "utility" },
  { name: LogStatsName.UltimatesUsed, abbr: "ULT ▶", labelKey: "matches.stat.ultimatesUsed", format: "int", group: "utility" },
  { name: LogStatsName.HeroTimePlayed, abbr: "TIME", labelKey: "matches.stat.heroTimePlayed", format: "duration", group: "utility" },

  // ── Accuracy / precision ────────────────────────────────────────────────
  { name: LogStatsName.WeaponAccuracy, abbr: "ACC", labelKey: "matches.stat.weaponAccuracy", format: "percent", group: "accuracy" },
  { name: LogStatsName.CriticalHits, abbr: "CRIT", labelKey: "matches.stat.criticalHits", format: "thousands", group: "accuracy" },
  { name: LogStatsName.CriticalHitAccuracy, abbr: "CRIT %", labelKey: "matches.stat.criticalHitAccuracy", format: "percent", group: "accuracy" },
  { name: LogStatsName.ScopedAccuracy, abbr: "SC ACC", labelKey: "matches.stat.scopedAccuracy", format: "percent", group: "accuracy" },
  { name: LogStatsName.ScopedCriticalHitAccuracy, abbr: "SC CRIT %", labelKey: "matches.stat.scopedCriticalHitAccuracy", format: "percent", group: "accuracy" },
  { name: LogStatsName.ScopedCriticalHitKills, abbr: "SC CRIT K", labelKey: "matches.stat.scopedCriticalHitKills", format: "int", group: "accuracy" },
  { name: LogStatsName.ShotsFired, abbr: "SHOTS", labelKey: "matches.stat.shotsFired", format: "thousands", group: "accuracy" },
  { name: LogStatsName.ShotsHit, abbr: "HITS", labelKey: "matches.stat.shotsHit", format: "thousands", group: "accuracy" },
  { name: LogStatsName.ShotsMissed, abbr: "MISS", labelKey: "matches.stat.shotsMissed", format: "thousands", group: "accuracy", reverted: true }
];

export const STAT_META: Record<string, StatMeta> = META.reduce<Record<string, StatMeta>>((acc, meta) => {
  acc[meta.name] = meta;
  return acc;
}, {});

/** Per-group accent (css var expression) used for micro-bars and chart marks. */
export const GROUP_COLOR: Record<StatGroup, string> = {
  combat: "var(--aqt-teal)",
  damage: "var(--aqt-damage)",
  tanking: "var(--aqt-blue)",
  healing: "var(--aqt-support)",
  utility: "var(--aqt-violet)",
  accuracy: "var(--aqt-amber)"
};

// ── Formatting ──────────────────────────────────────────────────────────────

const numberFmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

function formatDuration(secondsRaw: number): string {
  const seconds = Math.max(0, Math.floor(secondsRaw));
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

/**
 * Format a stat value for display. Accuracy stats are stored as a 0–1 fraction
 * (mirrors the heroes stat table convention); values > 1 are treated as absent.
 */
export function formatStat(name: LogStatsName, value: number | undefined | null): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const format = STAT_META[name]?.format ?? "int";
  switch (format) {
    case "percent":
      if (value > 1.0001) return "—";
      return `${(value * 100).toFixed(1)}%`;
    case "duration":
      return formatDuration(value);
    case "thousands":
      return numberFmt.format(Math.round(value));
    case "float":
      return numberFmt.format(Number(value.toFixed(2)));
    case "int":
    default:
      return numberFmt.format(Math.round(value));
  }
}

// ── Column presets ────────────────────────────────────────────────────────────

export type PresetKey = "overview" | "combat" | "damage" | "healing" | "accuracy" | "utility" | "all";

export const PRESET_ORDER: PresetKey[] = [
  "overview",
  "combat",
  "damage",
  "healing",
  "accuracy",
  "utility",
  "all"
];

const OVERVIEW: LogStatsName[] = [
  LogStatsName.FinalBlows,
  LogStatsName.Eliminations,
  LogStatsName.Deaths,
  LogStatsName.Assists,
  LogStatsName.KD,
  LogStatsName.KDA,
  LogStatsName.SoloKills,
  LogStatsName.HeroDamageDealt,
  LogStatsName.HealingDealt,
  LogStatsName.DamageBlocked,
  LogStatsName.DamageDelta,
  LogStatsName.UltimatesUsed
];

const COMBAT: LogStatsName[] = [
  LogStatsName.Eliminations,
  LogStatsName.FinalBlows,
  LogStatsName.Deaths,
  LogStatsName.Assists,
  LogStatsName.KD,
  LogStatsName.KDA,
  LogStatsName.SoloKills,
  LogStatsName.ObjectiveKills,
  LogStatsName.Multikills,
  LogStatsName.MultikillBest,
  LogStatsName.FirstPicks,
  LogStatsName.FirstDeaths,
  LogStatsName.UltimateKills,
  LogStatsName.SupportKills,
  LogStatsName.EnvironmentalKills
];

const DAMAGE: LogStatsName[] = [
  LogStatsName.HeroDamageDealt,
  LogStatsName.AllDamageDealt,
  LogStatsName.BarrierDamageDealt,
  LogStatsName.DamageFB,
  LogStatsName.DamageDelta,
  LogStatsName.DamageTaken,
  LogStatsName.DamageBlocked,
  LogStatsName.SelfHealing
];

const HEALING: LogStatsName[] = [
  LogStatsName.HealingDealt,
  LogStatsName.HealingReceived,
  LogStatsName.SelfHealing,
  LogStatsName.DefensiveAssists,
  LogStatsName.OffensiveAssists,
  LogStatsName.DamageBlocked,
  LogStatsName.DamageTaken
];

const ACCURACY: LogStatsName[] = [
  LogStatsName.WeaponAccuracy,
  LogStatsName.CriticalHits,
  LogStatsName.CriticalHitAccuracy,
  LogStatsName.ScopedAccuracy,
  LogStatsName.ScopedCriticalHitAccuracy,
  LogStatsName.ScopedCriticalHitKills,
  LogStatsName.ShotsFired,
  LogStatsName.ShotsHit,
  LogStatsName.ShotsMissed
];

const UTILITY: LogStatsName[] = [
  LogStatsName.UltimatesEarned,
  LogStatsName.UltimatesUsed,
  LogStatsName.ObjectiveKills,
  LogStatsName.FirstPicks,
  LogStatsName.FirstDeaths,
  LogStatsName.UltimateKills,
  LogStatsName.SupportKills,
  LogStatsName.EnvironmentalKills,
  LogStatsName.EnvironmentalDeaths,
  LogStatsName.HeroTimePlayed
];

// "All" = every catalogued stat, grouped in the catalogue's declared order.
const ALL: LogStatsName[] = META.map((m) => m.name);

export const COLUMN_PRESETS: Record<PresetKey, LogStatsName[]> = {
  overview: OVERVIEW,
  combat: COMBAT,
  damage: DAMAGE,
  healing: HEALING,
  accuracy: ACCURACY,
  utility: UTILITY,
  all: ALL
};

// ── Team comparison + leaders ────────────────────────────────────────────────

/** Stats shown in the head-to-head team comparison ("tale of the tape"). */
export const COMPARISON_STATS: LogStatsName[] = [
  LogStatsName.Eliminations,
  LogStatsName.FinalBlows,
  LogStatsName.Deaths,
  LogStatsName.Assists,
  LogStatsName.HeroDamageDealt,
  LogStatsName.HealingDealt,
  LogStatsName.DamageTaken,
  LogStatsName.DamageBlocked,
  LogStatsName.SoloKills,
  LogStatsName.UltimatesUsed
];

/** Individual match leaders (highlighted top performer per stat). */
export const LEADER_STATS: LogStatsName[] = [
  LogStatsName.HeroDamageDealt,
  LogStatsName.HealingDealt,
  LogStatsName.DamageBlocked,
  LogStatsName.Eliminations,
  LogStatsName.KDA,
  LogStatsName.FinalBlows
];

// ── Aggregation helpers ───────────────────────────────────────────────────────

export function playerStat(player: PlayerWithStats, round: number, name: LogStatsName): number {
  const value = player.stats?.[round]?.[name];
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

/** Players who actually fielded a hero in the given round (played the round). */
export function activePlayers(team: TeamWithStats, round: number): PlayerWithStats[] {
  return team.players.filter((player) => (player.heroes?.[round]?.length ?? 0) > 0);
}

export function teamTotal(team: TeamWithStats, round: number, name: LogStatsName): number {
  return activePlayers(team, round).reduce((sum, player) => sum + playerStat(player, round, name), 0);
}

/**
 * Per-column max across the active players of both teams — used to scale the
 * inline magnitude micro-bars consistently home vs away.
 */
export function columnMaxima(
  home: TeamWithStats,
  away: TeamWithStats,
  round: number,
  names: LogStatsName[]
): Record<string, number> {
  const players = [...activePlayers(home, round), ...activePlayers(away, round)];
  const out: Record<string, number> = {};
  for (const name of names) {
    let max = 0;
    for (const player of players) {
      max = Math.max(max, playerStat(player, round, name));
    }
    out[name] = max;
  }
  return out;
}

export interface StatLeader {
  player: PlayerWithStats;
  side: "home" | "away";
  value: number;
}

/** The single best player (highest value) across both teams for a stat. */
export function findLeader(
  home: TeamWithStats,
  away: TeamWithStats,
  round: number,
  name: LogStatsName
): StatLeader | null {
  let best: StatLeader | null = null;
  const consider = (player: PlayerWithStats, side: "home" | "away") => {
    const value = playerStat(player, round, name);
    if (value <= 0) return;
    if (!best || value > best.value) best = { player, side, value };
  };
  activePlayers(home, round).forEach((player) => consider(player, "home"));
  activePlayers(away, round).forEach((player) => consider(player, "away"));
  return best;
}

/** Round keys present in the match data (0 = whole match, then per-round). */
export function availableRounds(home: TeamWithStats, away: TeamWithStats): number[] {
  const rounds = new Set<number>();
  for (const team of [home, away]) {
    for (const player of team.players) {
      for (const key of Object.keys(player.stats ?? {})) {
        const round = Number(key);
        if (Number.isFinite(round)) rounds.add(round);
      }
    }
  }
  return [...rounds].sort((a, b) => a - b);
}
