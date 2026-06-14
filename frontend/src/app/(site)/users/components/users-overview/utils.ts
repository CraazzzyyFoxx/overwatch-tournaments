import { LogStatsName } from "@/types/stats.types";
import { UserRoleType } from "@/types/user.types";
import {
  clampDivisionToGrid,
  getDefaultDivisionGrid,
  getDivisionOptions,
} from "@/lib/division-grid";

export { getDivisionOptions };

export const ROLE_OPTIONS: Array<{ value: "all" | UserRoleType; label: string }> = [
  { value: "all", label: "All roles" },
  { value: "Tank", label: "Tank" },
  { value: "Damage", label: "Damage" },
  { value: "Support", label: "Support" }
];

export const SORT_OPTIONS = [
  { value: "name", label: "Name" },
  { value: "tournaments_count", label: "Tournaments" },
  { value: "achievements_count", label: "Achievements" },
  { value: "avg_placement", label: "Avg placement" }
] as const;

export type UsersOverviewSortValue = (typeof SORT_OPTIONS)[number]["value"];
export type UsersOverviewOrderValue = "asc" | "desc";

export const HERO_METRIC_LABELS: Record<string, string> = {
  [LogStatsName.Eliminations]: "Elims",
  [LogStatsName.FinalBlows]: "FB",
  [LogStatsName.HeroDamageDealt]: "Dmg",
  [LogStatsName.HealingDealt]: "Heal"
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

export const formatPlaytime = (seconds: number): string => {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return `${hours}h ${minutes}m ${secs}s`;
};
