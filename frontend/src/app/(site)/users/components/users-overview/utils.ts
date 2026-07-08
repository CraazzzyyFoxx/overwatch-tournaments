import type { useTranslations } from "next-intl";

import { LogStatsName } from "@/types/stats.types";
import { UserRoleType } from "@/types/user.types";
import {
  clampDivisionToGrid,
  getDefaultDivisionGrid,
  getDivisionOptions,
} from "@/lib/division-grid";

export { getDivisionOptions };

// Loose translator alias matching next-intl's `useTranslations()` return type so
// callers can hand their `t` straight through (strictFunctionTypes-safe).
export type Translate = ReturnType<typeof useTranslations>;

// Maps a role type to its shared `common.roles.*` message key (dps = "Damage").
export const ROLE_LABEL_KEY: Record<
  UserRoleType,
  "common.roles.tank" | "common.roles.dps" | "common.roles.support"
> = {
  Tank: "common.roles.tank",
  Damage: "common.roles.dps",
  Support: "common.roles.support"
};

type RoleOptionLabelKey = "common.all" | (typeof ROLE_LABEL_KEY)[UserRoleType];

export const ROLE_OPTIONS: Array<{ value: "all" | UserRoleType; labelKey: RoleOptionLabelKey }> = [
  { value: "all", labelKey: "common.all" },
  { value: "Tank", labelKey: "common.roles.tank" },
  { value: "Damage", labelKey: "common.roles.dps" },
  { value: "Support", labelKey: "common.roles.support" }
];

export const SORT_OPTIONS = [
  { value: "name", labelKey: "users.list.sort.name" },
  { value: "tournaments_count", labelKey: "users.list.sort.tournaments" },
  { value: "achievements_count", labelKey: "users.list.sort.achievements" },
  { value: "avg_placement", labelKey: "users.list.sort.avgPlacement" }
] as const;

export type UsersOverviewSortValue = (typeof SORT_OPTIONS)[number]["value"];
export type UsersOverviewOrderValue = "asc" | "desc";

export type HeroMetricLabelKey =
  | "users.list.heroMetrics.elims"
  | "users.list.heroMetrics.fb"
  | "users.list.heroMetrics.dmg"
  | "users.list.heroMetrics.heal";

// Maps a raw log-stat name to its compact metric message key (or undefined for
// names without a localized label, in which case the raw name is shown).
export const HERO_METRIC_LABEL_KEYS: Record<string, HeroMetricLabelKey> = {
  [LogStatsName.Eliminations]: "users.list.heroMetrics.elims",
  [LogStatsName.FinalBlows]: "users.list.heroMetrics.fb",
  [LogStatsName.HeroDamageDealt]: "users.list.heroMetrics.dmg",
  [LogStatsName.HealingDealt]: "users.list.heroMetrics.heal"
};

export const parsePositiveInt = (value: string | null, fallback: number): number => {
  if (!value) return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  return Math.floor(parsed);
};

export const parseOptionalInt = (value: string | null): number | undefined => {
  if (!value) return undefined;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return undefined;
  return Math.floor(parsed);
};

export const clampDivision = (value: number | undefined): number | undefined => {
  return clampDivisionToGrid(getDefaultDivisionGrid(), value);
};

export const parseSortValue = (value: string | null): UsersOverviewSortValue => {
  if (!value) return "name";
  const sortValues = SORT_OPTIONS.map((option) => option.value);
  return sortValues.includes(value as UsersOverviewSortValue) ? (value as UsersOverviewSortValue) : "name";
};

export const parseOrderValue = (value: string | null): UsersOverviewOrderValue => {
  return value === "desc" ? "desc" : "asc";
};

export const toUserSlug = (name: string): string => name.replace("#", "-");

export const formatOptional = (value: number | null): string => {
  if (value === null) return "-";
  return value.toFixed(2);
};

export const formatPlaytime = (seconds: number, t: Translate): string => {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return t("users.list.hero.playtimeFormat", {
    h: String(hours),
    m: String(minutes),
    s: String(secs)
  });
};
