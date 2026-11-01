import { characterClass } from "@/lib/catalog/attrs";
import { formatStat as formatStatValue, type StatFormatter } from "@/lib/stats/format";
import { LogStatsName } from "../stat-names";
import type { OwPlayer, OwTeam } from "./view";

export type MatchStatsTeam = OwTeam;
export type MatchStatsPlayer = OwPlayer;

/**
 * Single source of truth for the Overwatch match-statistics surface.
 *
 * A native match carries every fact at every grain; `owMatchView` re-keys a duel's member facts by segment and
 * stat code, and this module drives the expanded views (column presets, team comparison, leader cards,
 * contribution chart) from one declarative catalogue so formatting/labels stay consistent. The catalogue is the
 * module's own: which stats read as a column, their shorthand and which direction is better is Overwatch
 * presentation, not platform vocabulary.
 */

type StatFormat = "int" | "float" | "thousands" | "percent" | "duration";

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
  { name: LogStatsName.UltimatesEarned, abbr: "ULT CHG", labelKey: "matches.stat.ultimatesEarned", format: "int", group: "utility" },
  { name: LogStatsName.UltimatesUsed, abbr: "ULT", labelKey: "matches.stat.ultimatesUsed", format: "int", group: "utility" },
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

/** The module's display shorthands onto the platform's `value_format`s (`thousands` is an integer). */
const VALUE_FORMAT = {
  int: "integer",
  float: "decimal",
  thousands: "integer",
  percent: "percent",
  duration: "duration"
} as const satisfies Record<StatFormat, "integer" | "decimal" | "percent" | "duration">;

/**
 * Format a stat value for display through the platform formatter (`lib/stats/format`): accuracy stats are
 * 0–1 fractions (values > 1 read as absent), durations are seconds. A stat the catalogue does not know prints
 * as an integer. The caller supplies its locale's formatter (`useFormatter()` / `await getFormatter()`).
 */
export function formatStat(name: LogStatsName, value: number | undefined | null, formatter: StatFormatter): string {
  return formatStatValue({ value_format: VALUE_FORMAT[STAT_META[name]?.format ?? "int"] }, value, formatter);
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

/**
 * A run of a preset's columns under one heading. A preset of one band draws no band row (a heading
 * over every column says nothing); `labelKey` is then `null`.
 */
export interface PresetBand {
  labelKey: string | null;
  columns: LogStatsName[];
}

const band = (labelKey: string | null, columns: LogStatsName[]): PresetBand => ({ labelKey, columns });

const OVERVIEW: PresetBand[] = [
  band("matches.band.combat", [
    LogStatsName.FinalBlows,
    LogStatsName.Eliminations,
    LogStatsName.Deaths,
    LogStatsName.Assists,
    LogStatsName.KD,
    LogStatsName.KDA,
    LogStatsName.SoloKills
  ]),
  band("matches.band.output", [
    LogStatsName.HeroDamageDealt,
    LogStatsName.HealingDealt,
    LogStatsName.DamageBlocked,
    LogStatsName.DamageDelta
  ]),
  band("matches.band.ults", [LogStatsName.UltimatesUsed])
];

const COMBAT: PresetBand[] = [
  band(null, [
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
  ])
];

const DAMAGE: PresetBand[] = [
  band("matches.band.dealt", [
    LogStatsName.HeroDamageDealt,
    LogStatsName.AllDamageDealt,
    LogStatsName.BarrierDamageDealt,
    LogStatsName.DamageFB,
    LogStatsName.DamageDelta
  ]),
  band("matches.band.tanking", [LogStatsName.DamageTaken, LogStatsName.DamageBlocked, LogStatsName.SelfHealing])
];

const HEALING: PresetBand[] = [
  band(null, [
    LogStatsName.HealingDealt,
    LogStatsName.HealingReceived,
    LogStatsName.SelfHealing,
    LogStatsName.DefensiveAssists,
    LogStatsName.OffensiveAssists,
    LogStatsName.DamageBlocked,
    LogStatsName.DamageTaken
  ])
];

const ACCURACY: PresetBand[] = [
  band(null, [
    LogStatsName.WeaponAccuracy,
    LogStatsName.CriticalHits,
    LogStatsName.CriticalHitAccuracy,
    LogStatsName.ScopedAccuracy,
    LogStatsName.ScopedCriticalHitAccuracy,
    LogStatsName.ScopedCriticalHitKills,
    LogStatsName.ShotsFired,
    LogStatsName.ShotsHit,
    LogStatsName.ShotsMissed
  ])
];

const UTILITY: PresetBand[] = [
  band(null, [
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
  ])
];

// "All" = every catalogued stat, one band per group in the catalogue's declared order.
const ALL: PresetBand[] = META.reduce<PresetBand[]>((bands, meta) => {
  const last = bands.at(-1);
  const labelKey = `matches.group.${meta.group}`;
  if (last?.labelKey === labelKey) last.columns.push(meta.name);
  else bands.push(band(labelKey, [meta.name]));
  return bands;
}, []);

export const PRESET_BANDS: Record<PresetKey, PresetBand[]> = {
  overview: OVERVIEW,
  combat: COMBAT,
  damage: DAMAGE,
  healing: HEALING,
  accuracy: ACCURACY,
  utility: UTILITY,
  all: ALL
};

export const COLUMN_PRESETS = Object.fromEntries(
  PRESET_ORDER.map((key) => [key, PRESET_BANDS[key].flatMap((entry) => entry.columns)])
) as Record<PresetKey, LogStatsName[]>;

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

export function playerStat(player: Pick<MatchStatsPlayer, "stats">, round: number, name: LogStatsName): number {
  const value = player.stats?.[round]?.[name];
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

/** Official per-map MVP placement: the `impact_rank` fact, absent for unscored players (never a placement).
 * Mirrors `resolveMvpPlacement` in `./mvp` so a player's MVP badge agrees everywhere it appears. */
export function resolveMatchMvpPlacement(player: Pick<MatchStatsPlayer, "stats">, round: number): number | null {
  const rank = player.stats?.[round]?.[LogStatsName.ImpactRank];
  return typeof rank === "number" && Number.isFinite(rank) ? rank : null;
}

/** Native observed players, including stat-only rows with no resolved hero. */
export function activePlayers(team: Pick<MatchStatsTeam, "players"> | null, round: number): MatchStatsPlayer[] {
  return team?.players.filter(
    (player) => round === 0 || player.stats?.[round] != null || (player.heroes?.[round]?.length ?? 0) > 0
  ) ?? [];
}

export function teamTotal(team: Pick<MatchStatsTeam, "players">, round: number, name: LogStatsName): number {
  return activePlayers(team, round).reduce((sum, player) => sum + playerStat(player, round, name), 0);
}

/** What a team total of a stat is: a sum, a ratio of sums, the best single value, or nothing that adds up. */
const TEAM_RATIO: Partial<Record<LogStatsName, { kills: LogStatsName[]; per: LogStatsName }>> = {
  [LogStatsName.KD]: { kills: [LogStatsName.Eliminations], per: LogStatsName.Deaths },
  [LogStatsName.KDA]: { kills: [LogStatsName.Eliminations, LogStatsName.Assists], per: LogStatsName.Deaths }
};
const TEAM_MAX: Partial<Record<LogStatsName, true>> = { [LogStatsName.MultikillBest]: true };
/** Per-unit rates: averaging them over a team would invent a number. */
const TEAM_NONE: Partial<Record<LogStatsName, true>> = { [LogStatsName.DamageFB]: true, [LogStatsName.HeroTimePlayed]: true };

/**
 * A team's line under a scoreboard column: counts add up, K/D and KA/D are ratios of the summed counts, the best
 * multikill is the best one, and a percentage, a duration or a per-unit rate has no team value (`null`, drawn as
 * nothing — a missing total is not a dash).
 */
export function teamAggregate(team: Pick<MatchStatsTeam, "players">, round: number, name: LogStatsName): number | null {
  const ratio = TEAM_RATIO[name];
  if (ratio) {
    const per = teamTotal(team, round, ratio.per);
    return per > 0 ? ratio.kills.reduce((sum, kill) => sum + teamTotal(team, round, kill), 0) / per : null;
  }
  if (TEAM_MAX[name]) return Math.max(0, ...activePlayers(team, round).map((player) => playerStat(player, round, name)));
  const format = STAT_META[name]?.format;
  if (TEAM_NONE[name] || format === "percent" || format === "duration") return null;
  return teamTotal(team, round, name);
}

// ── Character classes (the Overwatch roles a scoreboard orders by) ────────────

/** The catalogue's class codes in the order a team is read: tank, then damage, then support. */
export const CLASS_ORDER: readonly string[] = ["tank", "damage", "support"];

/**
 * The class of the character a player spent the most time on in `round` (the whole match when the round has no
 * stint of its own), lowercased; `null` when the catalogue declares none. Display only: a class is never a role
 * the player was assigned.
 */
export function playerClass(player: Pick<MatchStatsPlayer, "heroTimes">, round: number): string | null {
  const main = (player.heroTimes[round]?.length ? player.heroTimes[round] : player.heroTimes[0])?.[0]?.entity;
  return characterClass(main)?.trim().toLowerCase() || null;
}

/** Tank → damage → support, then by the round's MVP placement (unscored last), then by member id. */
export function compareByClass(round: number) {
  const order = (player: MatchStatsPlayer) => {
    const index = CLASS_ORDER.indexOf(playerClass(player, 0) ?? "");
    return index < 0 ? CLASS_ORDER.length : index;
  };
  const placement = (player: MatchStatsPlayer) => resolveMatchMvpPlacement(player, round) ?? Number.POSITIVE_INFINITY;
  return (a: MatchStatsPlayer, b: MatchStatsPlayer) =>
    order(a) - order(b) || placement(a) - placement(b) || a.workspace_member_id - b.workspace_member_id;
}

/**
 * Per-column max across the active players of both teams — used to scale the
 * inline magnitude micro-bars consistently home vs away.
 */
export function columnMaxima(
  home: Pick<MatchStatsTeam, "players"> | null,
  away: Pick<MatchStatsTeam, "players"> | null,
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
  player: MatchStatsPlayer;
  side: "home" | "away";
  value: number;
}

/** The single best player (highest value) across both teams for a stat. */
export function findLeader(
  home: MatchStatsTeam,
  away: MatchStatsTeam,
  round: number,
  name: LogStatsName
): StatLeader | null {
  let best: StatLeader | null = null;
  const consider = (player: MatchStatsPlayer, side: "home" | "away") => {
    const value = playerStat(player, round, name);
    if (value <= 0) return;
    if (!best || value > best.value) best = { player, side, value };
  };
  activePlayers(home, round).forEach((player) => consider(player, "home"));
  activePlayers(away, round).forEach((player) => consider(player, "away"));
  return best;
}

/** Round keys present in the match data (0 = whole match, then per-round). */
export function availableRounds(home: MatchStatsTeam | null, away: MatchStatsTeam | null): number[] {
  const rounds = new Set<number>();
  for (const team of [home, away]) {
    if (team == null) continue;
    for (const player of team.players) {
      for (const key of Object.keys(player.stats ?? {})) {
        const round = Number(key);
        if (Number.isFinite(round)) rounds.add(round);
      }
    }
  }
  return [...rounds].sort((a, b) => a - b);
}
