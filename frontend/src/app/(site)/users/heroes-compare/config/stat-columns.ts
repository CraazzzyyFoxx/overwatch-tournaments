import { HeroLeaderboardEntry } from "@/types/hero.types";

export type StatKey = string;

export interface StatColumnDef {
  key: StatKey;
  shortLabel: string;
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
  per10_eliminations:      { key: "per10_eliminations",      shortLabel: "Elims / 10",       ascending: false, formatValue: _fmt.count, barColor: "bg-sky-400/65",     accentColor: "bg-sky-400",     getValue: _k("per10_eliminations") },
  per10_healing:           { key: "per10_healing",           shortLabel: "Healing / 10",     ascending: false, formatValue: _fmt.large, barColor: "bg-emerald-400/65", accentColor: "bg-emerald-400", getValue: _k("per10_healing") },
  per10_damage:            { key: "per10_damage",            shortLabel: "Damage / 10",      ascending: false, formatValue: _fmt.large, barColor: "bg-rose-400/65",    accentColor: "bg-rose-400",    getValue: _k("per10_damage") },
  per10_deaths:            { key: "per10_deaths",            shortLabel: "Deaths / 10",      ascending: true,  formatValue: _fmt.count, barColor: "bg-orange-400/65",  accentColor: "bg-orange-400",  getValue: _k("per10_deaths") },
  kd:                      { key: "kd",                      shortLabel: "K/D",              ascending: false, formatValue: _fmt.ratio, barColor: "bg-amber-400/65",   accentColor: "bg-amber-400",   getValue: _k("kd") },
  kda:                     { key: "kda",                     shortLabel: "KDA (Elim/D)",     ascending: false, formatValue: _fmt.ratio, barColor: "bg-lime-400/65",    accentColor: "bg-lime-400",    getValue: _k("kda") },
  per10_final_blows:       { key: "per10_final_blows",       shortLabel: "Final Blows / 10", ascending: false, formatValue: _fmt.count, barColor: "bg-yellow-400/65",  accentColor: "bg-yellow-400",  getValue: _k("per10_final_blows") },
  per10_damage_blocked:    { key: "per10_damage_blocked",    shortLabel: "Blocked / 10",     ascending: false, formatValue: _fmt.large, barColor: "bg-blue-400/65",    accentColor: "bg-blue-400",    getValue: _k("per10_damage_blocked") },
  per10_solo_kills:        { key: "per10_solo_kills",        shortLabel: "Solo Kills / 10",  ascending: false, formatValue: _fmt.count, barColor: "bg-red-400/65",     accentColor: "bg-red-400",     getValue: _k("per10_solo_kills") },
  per10_obj_kills:         { key: "per10_obj_kills",         shortLabel: "Obj Kills / 10",   ascending: false, formatValue: _fmt.count, barColor: "bg-teal-400/65",    accentColor: "bg-teal-400",    getValue: _k("per10_obj_kills") },
  per10_defensive_assists: { key: "per10_defensive_assists", shortLabel: "Def Assists / 10", ascending: false, formatValue: _fmt.count, barColor: "bg-cyan-400/65",    accentColor: "bg-cyan-400",    getValue: _k("per10_defensive_assists") },
  per10_offensive_assists: { key: "per10_offensive_assists", shortLabel: "Off Assists / 10", ascending: false, formatValue: _fmt.count, barColor: "bg-indigo-400/65",  accentColor: "bg-indigo-400",  getValue: _k("per10_offensive_assists") },
  per10_all_damage:        { key: "per10_all_damage",        shortLabel: "All Dmg / 10",     ascending: false, formatValue: _fmt.large, barColor: "bg-pink-400/65",    accentColor: "bg-pink-400",    getValue: _k("per10_all_damage") },
  per10_damage_taken:      { key: "per10_damage_taken",      shortLabel: "Dmg Taken / 10",   ascending: true,  formatValue: _fmt.large, barColor: "bg-stone-400/65",   accentColor: "bg-stone-400",   getValue: _k("per10_damage_taken") },
  per10_self_healing:      { key: "per10_self_healing",      shortLabel: "Self Heal / 10",   ascending: false, formatValue: _fmt.large, barColor: "bg-green-400/65",   accentColor: "bg-green-400",   getValue: _k("per10_self_healing") },
  per10_ultimates_used:    { key: "per10_ultimates_used",    shortLabel: "Ults / 10",        ascending: false, formatValue: _fmt.count, barColor: "bg-purple-400/65",  accentColor: "bg-purple-400",  getValue: _k("per10_ultimates_used") },
  per10_multikills:        { key: "per10_multikills",        shortLabel: "Multikills / 10",  ascending: false, formatValue: _fmt.count, barColor: "bg-fuchsia-400/65", accentColor: "bg-fuchsia-400", getValue: _k("per10_multikills") },
  per10_env_kills:         { key: "per10_env_kills",         shortLabel: "Env Kills / 10",   ascending: false, formatValue: _fmt.count, barColor: "bg-lime-400/65",    accentColor: "bg-lime-400",    getValue: _k("per10_env_kills") },
  per10_crit_hits:         { key: "per10_crit_hits",         shortLabel: "Crits / 10",       ascending: false, formatValue: _fmt.count, barColor: "bg-orange-400/65",  accentColor: "bg-orange-400",  getValue: _k("per10_crit_hits") },
  avg_weapon_accuracy:     { key: "avg_weapon_accuracy",     shortLabel: "Weapon Acc %",     ascending: false, formatValue: _fmt.pct,   barColor: "bg-violet-400/65",  accentColor: "bg-violet-400",  getValue: _k("avg_weapon_accuracy") },
  avg_crit_accuracy:       { key: "avg_crit_accuracy",       shortLabel: "Crit Acc %",       ascending: false, formatValue: _fmt.pct,   barColor: "bg-rose-400/65",    accentColor: "bg-rose-400",    getValue: _k("avg_crit_accuracy") },
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
