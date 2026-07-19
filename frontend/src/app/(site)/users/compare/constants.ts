import { LogStatsName } from "@/types/stats.types";
import { UserRoleType } from "@/types/user.types";
export { getDivisionOptions } from "@/lib/division-grid";

export type RoleFilterLabelKey =
  | "users.compare.allRoles"
  | "common.roles.tank"
  | "common.roles.dps"
  | "common.roles.support";

export const ROLE_FILTER_OPTIONS: Array<{
  value: "all" | UserRoleType;
  labelKey: RoleFilterLabelKey;
}> = [
  { value: "all", labelKey: "users.compare.allRoles" },
  { value: "Tank", labelKey: "common.roles.tank" },
  { value: "Damage", labelKey: "common.roles.dps" },
  { value: "Support", labelKey: "common.roles.support" }
];

export const HERO_COMPARE_STATS: LogStatsName[] = Object.values(LogStatsName).filter(
  (stat): stat is LogStatsName => stat !== LogStatsName.HeroTimePlayed && stat !== LogStatsName.Winrate
);
