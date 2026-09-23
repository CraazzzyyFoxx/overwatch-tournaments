import type { AppPermission } from "@/hooks/usePermissions";

/**
 * Permission sets that gate the admin area.
 *
 * These live in `lib/` rather than `components/admin/` because the public site
 * header needs `adminEntryPermissions` to decide whether to show the admin nav
 * entry — importing it from `components/admin/*` pulled the whole admin
 * navigation module (and its icon set) into the public bundle.
 */

export const overviewPermissions: AppPermission[] = [
  "tournament.read",
  "team.read",
  "player.read",
  "match.read",
  "standing.read",
  "user.read",
  "analytics.read",
];

export const accessUsersPermissions: AppPermission[] = ["auth_user.read"];
export const accessRolesPermissions: AppPermission[] = ["role.read"];
export const accessPermissionsPermissions: AppPermission[] = ["permission.read"];
export const accessApiKeysPermissions: AppPermission[] = ["team.create"];
export const accessAdminPermissions: AppPermission[] = [
  ...accessUsersPermissions,
  ...accessRolesPermissions,
  ...accessPermissionsPermissions,
  ...accessApiKeysPermissions,
];

/** Anything that makes the `/admin` entry point worth showing at all. */
export const adminEntryPermissions: AppPermission[] = [
  ...overviewPermissions,
  ...accessAdminPermissions,
  "achievement.read",
];
