import { HeroLeaderboardEntry } from "@/types/hero.types";

export type StatKey = string;

export type StatLabelKey =
  | "users.heroesCompare.stat.elims"
  | "users.heroesCompare.stat.healing"
  | "users.heroesCompare.stat.damage"
  | "users.heroesCompare.stat.deaths"
  | "users.heroesCompare.stat.kd"
  | "users.heroesCompare.stat.kda"
  | "users.heroesCompare.stat.finalBlows"
  | "users.heroesCompare.stat.blocked"
  | "users.heroesCompare.stat.soloKills"
  | "users.heroesCompare.stat.objKills"
  | "users.heroesCompare.stat.defAssists"
  | "users.heroesCompare.stat.offAssists"
  | "users.heroesCompare.stat.allDmg"
  | "users.heroesCompare.stat.dmgTaken"
  | "users.heroesCompare.stat.selfHeal"
  | "users.heroesCompare.stat.ults"
  | "users.heroesCompare.stat.multikills"
  | "users.heroesCompare.stat.envKills"
  | "users.heroesCompare.stat.crits"
  | "users.heroesCompare.stat.weaponAcc"
  | "users.heroesCompare.stat.critAcc";

export interface StatColumnDef {
  key: StatKey;
  labelKey: StatLabelKey;
  ascending: boolean;
  formatValue: (v: number) => string;
  barColor: string;
  accentColor: string;
  getValue: (e: HeroLeaderboardEntry) => number;
}

const _k =
  (field: keyof HeroLeaderboardEntry) =>
  (e: HeroLeaderboardEntry): number =>
    e[field] as number;

const _fmt = {
  count: (v: number) => v.toFixed(2),
  large: (v: number) => (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(0)),
  pct:   (v: number) => `${v.toFixed(1)}%`,
  ratio: (v: number) => v.toFixed(2),
} as const;

export const COL: Record<string, StatColumnDef> = {
  per10_eliminations:      { key: "per10_eliminations",      labelKey: "users.heroesCompare.stat.elims",      ascending: false, formatValue: _fmt.count, barColor: "bg-sky-400/65",     accentColor: "bg-sky-400",     getValue: _k("per10_eliminations") },
  per10_healing:           { key: "per10_healing",           labelKey: "users.heroesCompare.stat.healing",    ascending: false, formatValue: _fmt.large, barColor: "bg-emerald-400/65", accentColor: "bg-emerald-400", getValue: _k("per10_healing") },
  per10_damage:            { key: "per10_damage",            labelKey: "users.heroesCompare.stat.damage",     ascending: false, formatValue: _fmt.large, barColor: "bg-rose-400/65",    accentColor: "bg-rose-400",    getValue: _k("per10_damage") },
  per10_deaths:            { key: "per10_deaths",            labelKey: "users.heroesCompare.stat.deaths",     ascending: true,  formatValue: _fmt.count, barColor: "bg-orange-400/65",  accentColor: "bg-orange-400",  getValue: _k("per10_deaths") },
  kd:                      { key: "kd",                      labelKey: "users.heroesCompare.stat.kd",         ascending: false, formatValue: _fmt.ratio, barColor: "bg-amber-400/65",   accentColor: "bg-amber-400",   getValue: _k("kd") },
  kda:                     { key: "kda",                     labelKey: "users.heroesCompare.stat.kda",        ascending: false, formatValue: _fmt.ratio, barColor: "bg-lime-400/65",    accentColor: "bg-lime-400",    getValue: _k("kda") },
  per10_final_blows:       { key: "per10_final_blows",       labelKey: "users.heroesCompare.stat.finalBlows", ascending: false, formatValue: _fmt.count, barColor: "bg-yellow-400/65",  accentColor: "bg-yellow-400",  getValue: _k("per10_final_blows") },
  per10_damage_blocked:    { key: "per10_damage_blocked",    labelKey: "users.heroesCompare.stat.blocked",    ascending: false, formatValue: _fmt.large, barColor: "bg-blue-400/65",    accentColor: "bg-blue-400",    getValue: _k("per10_damage_blocked") },
  per10_solo_kills:        { key: "per10_solo_kills",        labelKey: "users.heroesCompare.stat.soloKills",  ascending: false, formatValue: _fmt.count, barColor: "bg-red-400/65",     accentColor: "bg-red-400",     getValue: _k("per10_solo_kills") },
  per10_obj_kills:         { key: "per10_obj_kills",         labelKey: "users.heroesCompare.stat.objKills",   ascending: false, formatValue: _fmt.count, barColor: "bg-teal-400/65",    accentColor: "bg-teal-400",    getValue: _k("per10_obj_kills") },
  per10_defensive_assists: { key: "per10_defensive_assists", labelKey: "users.heroesCompare.stat.defAssists", ascending: false, formatValue: _fmt.count, barColor: "bg-cyan-400/65",    accentColor: "bg-cyan-400",    getValue: _k("per10_defensive_assists") },
  per10_offensive_assists: { key: "per10_offensive_assists", labelKey: "users.heroesCompare.stat.offAssists", ascending: false, formatValue: _fmt.count, barColor: "bg-indigo-400/65",  accentColor: "bg-indigo-400",  getValue: _k("per10_offensive_assists") },
  per10_all_damage:        { key: "per10_all_damage",        labelKey: "users.heroesCompare.stat.allDmg",     ascending: false, formatValue: _fmt.large, barColor: "bg-pink-400/65",    accentColor: "bg-pink-400",    getValue: _k("per10_all_damage") },
  per10_damage_taken:      { key: "per10_damage_taken",      labelKey: "users.heroesCompare.stat.dmgTaken",   ascending: true,  formatValue: _fmt.large, barColor: "bg-stone-400/65",   accentColor: "bg-stone-400",   getValue: _k("per10_damage_taken") },
  per10_self_healing:      { key: "per10_self_healing",      labelKey: "users.heroesCompare.stat.selfHeal",   ascending: false, formatValue: _fmt.large, barColor: "bg-green-400/65",   accentColor: "bg-green-400",   getValue: _k("per10_self_healing") },
  per10_ultimates_used:    { key: "per10_ultimates_used",    labelKey: "users.heroesCompare.stat.ults",       ascending: false, formatValue: _fmt.count, barColor: "bg-purple-400/65",  accentColor: "bg-purple-400",  getValue: _k("per10_ultimates_used") },
  per10_multikills:        { key: "per10_multikills",        labelKey: "users.heroesCompare.stat.multikills", ascending: false, formatValue: _fmt.count, barColor: "bg-fuchsia-400/65", accentColor: "bg-fuchsia-400", getValue: _k("per10_multikills") },
  per10_env_kills:         { key: "per10_env_kills",         labelKey: "users.heroesCompare.stat.envKills",   ascending: false, formatValue: _fmt.count, barColor: "bg-lime-400/65",    accentColor: "bg-lime-400",    getValue: _k("per10_env_kills") },
  per10_crit_hits:         { key: "per10_crit_hits",         labelKey: "users.heroesCompare.stat.crits",      ascending: false, formatValue: _fmt.count, barColor: "bg-orange-400/65",  accentColor: "bg-orange-400",  getValue: _k("per10_crit_hits") },
  avg_weapon_accuracy:     { key: "avg_weapon_accuracy",     labelKey: "users.heroesCompare.stat.weaponAcc",  ascending: false, formatValue: _fmt.pct,   barColor: "bg-violet-400/65",  accentColor: "bg-violet-400",  getValue: _k("avg_weapon_accuracy") },
  avg_crit_accuracy:       { key: "avg_crit_accuracy",       labelKey: "users.heroesCompare.stat.critAcc",    ascending: false, formatValue: _fmt.pct,   barColor: "bg-rose-400/65",    accentColor: "bg-rose-400",    getValue: _k("avg_crit_accuracy") },
};

export const FIXED_COLUMNS_BY_ROLE: Record<string, StatKey[]> = {
  Damage:  ["per10_eliminations", "per10_damage", "per10_deaths", "kd"],
  Tank:    ["per10_eliminations", "per10_damage_blocked", "per10_damage", "per10_deaths"],
  Support: ["per10_eliminations", "per10_healing", "per10_damage", "per10_deaths"],
};

export const FIXED_COLUMNS_DEFAULT: StatKey[] = [
  "per10_eliminations", "per10_healing", "per10_damage", "per10_deaths",
];

export const DEFAULT_CUSTOM_BY_ROLE: Record<string, StatKey> = {
  Damage:  "per10_final_blows",
  Tank:    "per10_solo_kills",
  Support: "per10_final_blows",
};

export const DEFAULT_CUSTOM_KEY: StatKey = "per10_final_blows";

export const ALL_STAT_OPTIONS: StatColumnDef[] = Object.values(COL);

export const NUM_COLUMNS = 5;

export function getDefaultColumnKeys(role?: string | null): StatKey[] {
  const fixed = FIXED_COLUMNS_BY_ROLE[role ?? ""] ?? FIXED_COLUMNS_DEFAULT;
  return [...fixed, DEFAULT_CUSTOM_BY_ROLE[role ?? ""] ?? DEFAULT_CUSTOM_KEY];
}
