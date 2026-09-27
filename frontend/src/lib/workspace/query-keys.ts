import type { KeyPart } from "@/lib/query-keys";

/**
 * Keys for workspace membership, RBAC roles and the Discord/subscription
 * integrations a workspace configures. The balancer's own workspace config lives
 * in `lib/balancer/query-keys.ts` with the rest of the tool's keys.
 */
export const workspaceQueryKeys = {
  members: (workspaceId: KeyPart) => ["workspace", "members", workspaceId] as const,
  discordChannels: (workspaceId: KeyPart) =>
    ["workspace", workspaceId, "discord", "channels"] as const,
  discordGuild: (workspaceId: KeyPart) => ["workspace", workspaceId, "discord", "guild"] as const,
  discordRoles: (workspaceId: KeyPart) => ["workspace", workspaceId, "discord", "roles"] as const,
  discord: (workspaceId: KeyPart) => ["workspace", workspaceId, "discord"] as const,
  quotaUsage: (workspaceId: KeyPart) => ["workspace", workspaceId, "quota", "usage"] as const,
  memberList: (workspaceId: KeyPart) => ["workspace-members", workspaceId] as const,
  rbacRoles: (workspaceId: KeyPart) => ["workspace-rbac-roles", workspaceId] as const,
  rbacUsersAll: (workspaceId: KeyPart) => ["rbac-users", workspaceId, "all"] as const,
  subscriptionProviders: (workspaceId: KeyPart) =>
    ["subscription-providers", workspaceId] as const,
  subscriptionRequirement: (workspaceId: KeyPart) =>
    ["subscription-requirement", workspaceId] as const,
};
