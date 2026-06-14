import { describe, expect, it } from "bun:test";

import { getVisibleAdminNavigationGroups } from "@/components/admin/admin-navigation";

describe("admin navigation visibility", () => {
  it("shows workspace-admin entries when the access callback allows workspace-admin items", () => {
    const groups = getVisibleAdminNavigationGroups((item) => item.workspaceAdminVisible === true);
    const hrefs = groups.flatMap((group) => group.items.map((item) => item.href));

    expect(hrefs).toContain("/admin/divisions");
    expect(hrefs).toContain("/admin/workspaces");
    expect(hrefs).toContain("/admin/workspaces/members");
  });

  it("keeps global-only admin pages hidden when only workspace access is available", () => {
    const groups = getVisibleAdminNavigationGroups((item) => item.workspaceAdminVisible === true);
    const hrefs = groups.flatMap((group) => group.items.map((item) => item.href));

    expect(hrefs).not.toContain("/admin/access/users");
    expect(hrefs).not.toContain("/admin/access/oauth");
    expect(hrefs).not.toContain("/admin/access/permissions");
  });
});
