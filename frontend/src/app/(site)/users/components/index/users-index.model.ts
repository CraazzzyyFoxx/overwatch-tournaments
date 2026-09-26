import { ROLE_LABEL_KEY, type Translate } from "@/app/(site)/users/components/shared/list-utils";
import type { UserOverviewRoleDivision, UserRoleType } from "@/types/user.types";

export type SortValue = "name" | "tournaments_count" | "achievements_count" | "avg_placement";
export type OrderValue = "asc" | "desc";
export type ViewMode = "analytics" | "catalog";

type SortLabelKey =
  | "users.list.sort.name"
  | "users.list.sort.tournaments"
  | "users.list.sort.achievements"
  | "users.list.sort.avgPlacement";

export const SORT_OPTIONS: Array<{ value: SortValue; labelKey: SortLabelKey }> = [
  { value: "name", labelKey: "users.list.sort.name" },
  { value: "tournaments_count", labelKey: "users.list.sort.tournaments" },
  { value: "achievements_count", labelKey: "users.list.sort.achievements" },
  { value: "avg_placement", labelKey: "users.list.sort.avgPlacement" }
];

// The `Flex` chip filters on `role=Flex` — players whose declared roster role is
// literally flex. The read-only `stats.flex_count` chip rendered right next to it
// counts a strictly wider population ("plays anything": multi-role OR explicit
// flex), so the two numbers are meant to disagree. Do not "fix" one to match the
// other.
export const ROLE_FILTERS: Array<{
  value: "all" | UserRoleType;
  labelKey: "common.all" | (typeof ROLE_LABEL_KEY)[UserRoleType];
}> = [
  { value: "all", labelKey: "common.all" },
  { value: "Tank", labelKey: "common.roles.tank" },
  { value: "Damage", labelKey: "common.roles.damage" },
  { value: "Support", labelKey: "common.roles.support" },
  { value: "Flex", labelKey: "common.roles.flex" }
];

export const ALPHABET = ["#", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("")];

export const parseSort = (value: string | null): SortValue => {
  const allowed = SORT_OPTIONS.map((option) => option.value);
  return value && (allowed as string[]).includes(value) ? (value as SortValue) : "name";
};

export const parseOrder = (value: string | null): OrderValue => {
  return value === "desc" ? "desc" : "asc";
};

export const parseView = (value: string | null): ViewMode => {
  return value === "catalog" ? "catalog" : "analytics";
};

/** Splits `Player#1234` into the handle and its BattleTag discriminator. */
export function splitTag(name: string): { handle: string; tag: string | null } {
  const idx = name.lastIndexOf("#");
  if (idx === -1) {
    return { handle: name, tag: null };
  }
  return { handle: name.slice(0, idx), tag: name.slice(idx) };
}

/** One role, or "Flex · TAN / DAM" for a player who is ranked on several. */
export function primaryRoleLabel(roles: UserOverviewRoleDivision[], t: Translate): string {
  if (roles.length === 0) return t("users.list.roleLabel.unranked");
  if (roles.length === 1) return t(ROLE_LABEL_KEY[roles[0].role]);
  const abbr = roles.map((r) => t(ROLE_LABEL_KEY[r.role]).slice(0, 3).toUpperCase()).join(" / ");
  return `${t("common.roles.flex")} · ${abbr}`;
}

/**
 * Placement 1..30 mapped onto a 12%..100% bar — a longer bar is a better
 * finish. `warn` tints everything from 8th place down.
 */
export function placementWidth(placement: number | null): { width: number; warn: boolean } {
  if (placement === null || !Number.isFinite(placement)) {
    return { width: 0, warn: false };
  }
  const clamped = Math.max(1, Math.min(30, placement));
  const width = Math.round(((30 - clamped) / 29) * 88 + 12);
  return { width, warn: placement >= 8 };
}
