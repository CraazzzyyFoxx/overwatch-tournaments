import { describe, expect, it } from "bun:test";

import {
  canAccessAnyPermissionForProfile,
  hasAdminPanelAccessForProfile,
  hasWorkspacePermissionForProfile,
  type PermissionProfile,
} from "@/hooks/usePermissions";

function createProfile(overrides: Partial<PermissionProfile> = {}): PermissionProfile {
  return {
    isSuperuser: false,
    roles: [],
    permissions: [],
    workspaces: [],
    ...overrides,
  };
}

describe("usePermissions helpers", () => {
  it("keeps global permission access", () => {
    const profile = createProfile({
      permissions: ["tournament.read"],
    });

    expect(canAccessAnyPermissionForProfile(profile, ["tournament.read"], 42)).toBe(true);
  });

  it("grants workspace-scoped permission only in the matching workspace", () => {
    const profile = createProfile({
      workspaces: [
        {
          workspace_id: 7,
          memberRole: "member",
          permissions: ["team.read"],
        },
      ],
    });

    expect(hasWorkspacePermissionForProfile(profile, 7, "team.read")).toBe(true);
    expect(hasWorkspacePermissionForProfile(profile, 8, "team.read")).toBe(false);
  });

  it("treats workspace-specific access as sufficient when checking any workspace", () => {
    const profile = createProfile({
      workspaces: [
        {
          workspace_id: 9,
          memberRole: "admin",
          permissions: ["match.read"],
        },
      ],
    });

    expect(canAccessAnyPermissionForProfile(profile, ["match.read"])).toBe(true);
  });

  it("treats workspace admin wildcard as scoped to that workspace", () => {
    const profile = createProfile({
      workspaces: [
        {
          workspace_id: 11,
          memberRole: "admin",
          permissions: ["admin.*"],
        },
      ],
    });

    expect(hasWorkspacePermissionForProfile(profile, 11, "tournament.read")).toBe(true);
    expect(hasWorkspacePermissionForProfile(profile, 11, "team.import")).toBe(true);
    expect(hasWorkspacePermissionForProfile(profile, 12, "tournament.read")).toBe(false);
    expect(canAccessAnyPermissionForProfile(profile, ["map.read"])).toBe(true);
  });

  it("does not trust legacy workspace memberRole as a permission wildcard", () => {
    const profile = createProfile({
      workspaces: [
        {
          workspace_id: 13,
          memberRole: "admin",
          permissions: [],
        },
      ],
    });

    expect(hasWorkspacePermissionForProfile(profile, 13, "team.import")).toBe(false);
  });

  it("does not treat read-only permissions as admin panel access", () => {
    const profile = createProfile({
      permissions: ["tournament.read"],
      workspaces: [
        {
          workspace_id: 21,
          memberRole: "member",
          permissions: ["workspace.read", "workspace_member.read", "team.read"],
        },
      ],
    });

    expect(canAccessAnyPermissionForProfile(profile, ["tournament.read"], 21)).toBe(true);
    expect(hasAdminPanelAccessForProfile(profile, 21)).toBe(false);
    expect(hasAdminPanelAccessForProfile(profile)).toBe(false);
  });

  it("allows admin panel access when a scoped non-read permission exists", () => {
    const profile = createProfile({
      workspaces: [
        {
          workspace_id: 22,
          memberRole: "member",
          permissions: ["team.read", "team.update"],
        },
      ],
    });

    expect(hasAdminPanelAccessForProfile(profile, 22)).toBe(true);
    expect(hasAdminPanelAccessForProfile(profile, 23)).toBe(false);
  });

  it("allows admin panel access for wildcard permissions", () => {
    const profile = createProfile({
      workspaces: [
        {
          workspace_id: 24,
          memberRole: "owner",
          permissions: ["admin.*"],
        },
      ],
    });

    expect(hasAdminPanelAccessForProfile(profile, 24)).toBe(true);
  });
});
