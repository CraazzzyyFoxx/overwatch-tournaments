import type { KeyPart } from "@/lib/query-keys";

/**
 * Keys for achievements on both sides of the wall: the public catalogue and the
 * organizer's rule editor (rooted at `admin` because that is the surface the
 * rule mutations already invalidate). They live in one file because a rule edit
 * stales the public list, and a key spelled twice is a list that never updates.
 */
export const achievementQueryKeys = {
  users: (achievementId: KeyPart, page: KeyPart) =>
    ["achievement", "users", achievementId, page] as const,
  all: (workspaceId: KeyPart) => ["achievements", "all", workspaceId] as const,
  conditionTypes: (workspaceId: KeyPart) =>
    ["admin", "achievement-condition-types", workspaceId] as const,
  libraryRules: (workspaceId: KeyPart, sourceWorkspaceId: KeyPart) =>
    ["admin", "achievement-library-rules", workspaceId, sourceWorkspaceId] as const,
  libraryWorkspaces: (workspaceId: KeyPart) =>
    ["admin", "achievement-library-workspaces", workspaceId] as const,
  ruleUsersPage: (workspaceId: KeyPart, ruleId: KeyPart, tournamentId: KeyPart, sort: KeyPart, order: KeyPart) =>
    ["admin", "achievement-rule-users", workspaceId, ruleId, tournamentId, sort, order] as const,
  ruleUsers: (workspaceId: KeyPart, ruleId: KeyPart) =>
    ["admin", "achievement-rule-users", workspaceId, ruleId] as const,
  rule: (workspaceId: KeyPart, ruleId: KeyPart) =>
    ["admin", "achievement-rule", workspaceId, ruleId] as const,
  adminList: (workspaceId: KeyPart) => ["admin", "achievements", workspaceId] as const,
  overrides: (workspaceId: KeyPart, ruleId: KeyPart) =>
    ["admin", "overrides", workspaceId, ruleId] as const,
  overridesAll: (workspaceId: KeyPart) => ["admin", "overrides", workspaceId] as const,
};
