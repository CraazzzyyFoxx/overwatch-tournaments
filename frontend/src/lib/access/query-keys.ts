import type { KeyPart } from "@/lib/query-keys";

/**
 * Keys for the platform access console: roles, permission inventory, accounts
 * and per-account restrictions. Everything here is rooted at `access-admin`, so
 * a console write can drop one entity or the whole surface with one prefix.
 */
export const accessQueryKeys = {
  denies: (userId: KeyPart) => ["access-admin", "denies", userId] as const,
  oauthConnections: () => ["access-admin", "oauth-connections"] as const,
  permissionsInventory: () => ["access-admin", "permissions", "inventory"] as const,
  permissionsByScope: (scope: KeyPart) =>
    ["access-admin", "permissions", "scope", scope] as const,
  rolesAll: () => ["access-admin", "roles", "all"] as const,
  rolesByScope: (scope: KeyPart) => ["access-admin", "roles", "scope", scope] as const,
  role: (roleId: KeyPart) => ["access-admin", "roles", roleId] as const,
  roles: () => ["access-admin", "roles"] as const,
  user: (userId: KeyPart) => ["access-admin", "user", userId] as const,
  usersAll: () => ["access-admin", "users", "all"] as const,
  userOauthConnections: (userId: KeyPart) =>
    ["access-admin", "users", userId, "oauth-connections"] as const,
  userDetail: (userId: KeyPart) => ["access-admin", "users", userId] as const,
  users: () => ["access-admin", "users"] as const,
};
