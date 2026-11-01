import { METRICS, TIMED_STATS, type MetricContext } from "./model";

export type ColumnFormat = "int" | "pct" | "dec";
export type Stats = Record<string, number>;

export interface Column {
  key: string;
  /** `matches.deadlock.col.<key>` is the head, `matches.deadlock.colTitle.<key>` its full name. */
  value: (stats: Stats, ctx: MetricContext) => number | null;
  /** The team line from its players' stats; `null` where a team figure would not mean anything. */
  total: (players: readonly Stats[], ctx: MetricContext) => number | null;
  format: ColumnFormat;
  /** Whether the samples carry it, i.e. whether it has a value before the end of the match. */
  timed: boolean;
  /** Fewer is better (deaths, damage taken, souls lost). */
  fewer?: boolean;
  /** A magnitude micro-bar under the figure. */
  bar?: boolean;
}

export const sumOf = (players: readonly Stats[], code: string): number | null => {
  const values = players.map((stats) => stats[code]).filter((value) => value != null);
  return values.length ? values.reduce((a, b) => a + b, 0) : null;
};

const fact = (code: string, extra: Partial<Column> = {}): Column => ({
  key: code,
  value: (stats) => stats[code] ?? null,
  total: (players) => sumOf(players, code),
  format: "int",
  timed: code in TIMED_STATS,
  ...extra
});

const metric = (key: string, format: ColumnFormat, timed: boolean, total: Column["total"] = () => null, extra: Partial<Column> = {}): Column => ({
  key,
  value: (stats, ctx) => METRICS[key](stats, ctx),
  total,
  format,
  timed,
  ...extra
});

/** A team's figure of a per-minute metric: its sum over the minutes played so far. */
const perMinute = (code: string) => (players: readonly Stats[], ctx: MetricContext) => {
  const sum = sumOf(players, code);
  return sum == null || !ctx.minutes ? null : sum / ctx.minutes;
};
/** A team's rate: the ratio of its sums, never an average of rates. */
const teamRatio = (part: string, ...whole: string[]) => (players: readonly Stats[]) => {
  const p = sumOf(players, part);
  const w = whole.reduce((total, code) => total + (sumOf(players, code) ?? 0), 0);
  return p == null || w <= 0 ? null : p / w;
};

export const PRESETS = {
  overview: [
    fact("kills"),
    fact("deaths", { fewer: true }),
    fact("assists"),
    fact("net_worth", { bar: true }),
    metric("souls_per_min", "int", true, perMinute("net_worth")),
    fact("player_damage", { bar: true }),
    fact("boss_damage", { bar: true }),
    fact("player_healing", { bar: true })
  ],
  combat: [
    fact("player_damage", { bar: true }),
    metric("damage_per_min", "int", true, perMinute("player_damage")),
    metric("damage_per_life", "int", true),
    fact("player_damage_taken", { fewer: true }),
    metric("taken_per_life", "int", true, () => null, { fewer: true }),
    metric("accuracy", "pct", false, teamRatio("shots_hit", "shots_hit", "shots_missed")),
    metric("headshot_rate", "pct", false, teamRatio("hero_bullets_hit_crit", "hero_bullets_hit")),
    metric("kill_participation", "pct", true)
  ],
  economy: [
    fact("net_worth", { bar: true }),
    metric("souls_per_min", "int", true, perMinute("net_worth")),
    fact("creep_kills"),
    fact("neutral_kills"),
    fact("last_hits"),
    fact("denies"),
    fact("souls_players"),
    fact("souls_lost", { fewer: true })
  ],
  support: [
    fact("player_healing", { bar: true }),
    fact("self_healing"),
    fact("teammate_healing", { bar: true }),
    fact("player_barriering"),
    fact("damage_absorbed"),
    fact("damage_mitigated"),
    fact("heal_prevented")
  ]
} satisfies Record<string, Column[]>;

export type PresetKey = keyof typeof PRESETS;
export const PRESET_ORDER = Object.keys(PRESETS) as PresetKey[];
