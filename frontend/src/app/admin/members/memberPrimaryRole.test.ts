import { describe, expect, it } from "vitest";

import { memberPrimaryRole } from "@/app/admin/members/page";
import type { WorkspaceMember } from "@/types/workspace.types";

function member(roles: Array<{ name: string; is_system: boolean }>): WorkspaceMember {
  return {
    id: 1,
    workspace_id: 1,
    auth_user_id: 1,
    rbac_roles: roles.map((role, index) => ({ id: index + 1, ...role }))
  };
}

describe("memberPrimaryRole", () => {
  it("picks the highest-priority system role, ignoring custom ones", () => {
    expect(
      memberPrimaryRole(
        member([
          { name: "caster", is_system: false },
          { name: "player", is_system: true },
          { name: "owner", is_system: true }
        ])
      )
    ).toBe("owner");
  });

  it("returns the only system role held", () => {
    expect(memberPrimaryRole(member([{ name: "admin", is_system: true }]))).toBe("admin");
  });

  it("returns undefined for a member holding no system role", () => {
    // A custom role named after a system one must not be promoted, and a member
    // with no system role at all is a real state -- what "Fill missing roles" repairs.
    expect(
      memberPrimaryRole(
        member([
          { name: "caster", is_system: false },
          { name: "admin", is_system: false }
        ])
      )
    ).toBeUndefined();
  });
});
