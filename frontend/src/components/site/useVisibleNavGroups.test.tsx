import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import type { PermissionProfile } from "@/hooks/usePermissions";

const WORKSPACE_ID = 7;

const state = vi.hoisted(() => ({ user: null as unknown }));

// The workspace id is a literal here, not `WORKSPACE_ID`: vi hoists these
// factories above the const. A divergence fails loudly — permission lookups
// would miss the profile's only workspace.
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (select: (s: { currentWorkspaceId: number }) => unknown) =>
    select({ currentWorkspaceId: 7 })
}));
vi.mock("@/stores/auth-profile.store", () => ({
  useAuthProfileStore: (select: (s: { user: unknown; status: string }) => unknown) =>
    select({ user: state.user, status: "authenticated" })
}));

// Must follow the hoisted vi.mock calls above.
import { usePermissions } from "@/hooks/usePermissions";
import { useVisibleNavGroups } from "./useVisibleNavGroups";

interface Viewer {
  navKeys: string[];
  isWorkspaceAdmin: boolean;
  canManageAnyWorkspace: boolean;
}

/**
 * The nav tree and the admin-panel predicates as one viewer sees them. Both are
 * read in a single render so a future regression that ties them back together
 * (a mix grant that opens the admin entry) fails loudly in one probe.
 *
 * The probe *renders* its reading rather than assigning it to a closure
 * variable: writing to an outer binding during render is the side effect
 * `react-hooks/globals` forbids, and serialising it keeps the probe pure.
 */
function viewerWith(workspacePermissions: string[]): Viewer {
  const profile: PermissionProfile = {
    isSuperuser: false,
    roles: ["user"],
    permissions: [],
    workspaces: [{ workspace_id: WORKSPACE_ID, permissions: workspacePermissions }]
  };
  state.user = profile;

  function Probe() {
    const groups = useVisibleNavGroups();
    const { isWorkspaceAdmin, canManageAnyWorkspace } = usePermissions();
    const seen: Viewer = {
      navKeys: groups.flatMap((group) => group.items.map((item) => `${group.key}/${item.key}`)),
      isWorkspaceAdmin: isWorkspaceAdmin(WORKSPACE_ID),
      canManageAnyWorkspace: canManageAnyWorkspace()
    };
    return <script type="application/json">{JSON.stringify(seen)}</script>;
  }

  const markup = renderToStaticMarkup(<Probe />);
  const payload = markup.replace(/^<script type="application\/json">/, "").replace(/<\/script>$/, "");
  return JSON.parse(payload) as Viewer;
}

describe("useVisibleNavGroups", () => {
  it("shows Mixes under Matches to a member holding only custom_game.create, without admin access", () => {
    const viewer = viewerWith(["custom_game.create"]);

    expect(viewer.navKeys).toContain("matches/mixes");
    // Hosting a mix is member-level: it must not imply the admin panel.
    expect(viewer.navKeys).not.toContain("organization/admin");
    expect(viewer.isWorkspaceAdmin).toBe(false);
    expect(viewer.canManageAnyWorkspace).toBe(false);
  });

  it("still opens the admin entry for a real management permission", () => {
    const viewer = viewerWith(["team.update"]);

    expect(viewer.navKeys).toContain("organization/admin");
    expect(viewer.isWorkspaceAdmin).toBe(true);
    expect(viewer.canManageAnyWorkspace).toBe(true);
    // Viewing mixes needs no grant of its own, so it stays visible regardless.
    expect(viewer.navKeys).toContain("matches/mixes");
  });

  it("shows Mixes to a viewer with no workspace permissions at all", () => {
    const viewer = viewerWith([]);

    // Reading a mix used to need `custom_game.read`; it is open to everyone
    // now, so the entry survives even a grant-free profile.
    expect(viewer.navKeys).toContain("matches/mixes");
    expect(viewer.navKeys).toContain("matches/encounters");
    expect(viewer.navKeys).toContain("tournaments/tournaments");
    expect(viewer.navKeys).toContain("tournaments/analytics");
  });
});
