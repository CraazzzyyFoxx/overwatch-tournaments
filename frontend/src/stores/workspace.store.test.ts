import { describe, expect, it } from "bun:test";

import type { AuthProfile } from "@/stores/auth-profile.store";
import {
  filterAccessibleWorkspaces,
  resolveCurrentWorkspaceId,
} from "@/stores/workspace.store";
import type { Workspace } from "@/types/workspace.types";

function createWorkspace(id: number, name = `Workspace ${id}`): Workspace {
  return {
    id,
    slug: `workspace-${id}`,
    name,
    description: null,
    icon_url: null,
    is_active: true,
    default_division_grid_version_id: null,
    default_division_grid_version: null,
  };
}

function createProfile(workspaceIds: number[]): AuthProfile {
  return {
    username: "tester",
    avatarUrl: null,
    roles: [],
    permissions: [],
    isSuperuser: false,
    linkedPlayers: [],
    workspaces: workspaceIds.map((workspaceId) => ({
      workspace_id: workspaceId,
      slug: `workspace-${workspaceId}`,
      memberRole: workspaceId === workspaceIds[0] ? "admin" : "member",
      roles: [],
      permissions: [],
    })),
  };
}

describe("workspace store helpers", () => {
  it("filters workspaces to memberships for authenticated non-superusers", () => {
    const allWorkspaces = [createWorkspace(1), createWorkspace(2), createWorkspace(3)];
    const filtered = filterAccessibleWorkspaces(allWorkspaces, "authenticated", createProfile([1, 3]));

    expect(filtered.map((workspace) => workspace.id)).toEqual([1, 3]);
  });

  it("keeps all workspaces for anonymous users", () => {
    const allWorkspaces = [createWorkspace(1), createWorkspace(2)];

    expect(filterAccessibleWorkspaces(allWorkspaces, "anonymous")).toEqual(allWorkspaces);
  });

  it("replaces an inaccessible persisted workspace with the first accessible one", () => {
    const accessible = [createWorkspace(5), createWorkspace(8)];

    expect(resolveCurrentWorkspaceId(accessible, 99)).toBe(5);
  });
});
