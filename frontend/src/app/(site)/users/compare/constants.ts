import { LogStatsName } from "@/types/stats.types";
import { UserRoleType } from "@/types/user.types";
export { getDivisionOptions } from "@/lib/division-grid";

export type RoleFilterLabelKey =
  | "users.compare.allRoles"
  | "common.roles.tank"
  | "common.roles.damage"
  | "common.roles.support"
  | "common.roles.flex";

export const ROLE_FILTER_OPTIONS: Array<{
  value: "all" | UserRoleType;
  labelKey: RoleFilterLabelKey;
}> = [
  { value: "all", labelKey: "users.compare.allRoles" },
  { value: "Tank", labelKey: "common.roles.tank" },
  { value: "Damage", labelKey: "common.roles.damage" },
  { value: "Support", labelKey: "common.roles.support" },
  { value: "Flex", labelKey: "common.roles.flex" }
];

export const HERO_COMPARE_STATS: LogStatsName[] = Object.values(LogStatsName).filter(
  (stat): stat is LogStatsName => stat !== LogStatsName.HeroTimePlayed && stat !== LogStatsName.Winrate
);
