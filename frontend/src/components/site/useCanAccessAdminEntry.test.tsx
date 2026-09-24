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
import { useCanAccessAdminEntry } from "./useCanAccessAdminEntry";

interface Viewer {
  adminEntry: boolean;
  isWorkspaceAdmin: boolean;
  canManageAnyWorkspace: boolean;
}

/**
 * The header's admin entry and the admin-panel predicates as one viewer sees
 * them. Both are read in a single render so a future regression that ties them
 * back together (a mix grant that opens the admin entry) fails loudly in one
 * probe.
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
    const adminEntry = useCanAccessAdminEntry();
    const { isWorkspaceAdmin, canManageAnyWorkspace } = usePermissions();
    const seen: Viewer = {
      adminEntry,
      isWorkspaceAdmin: isWorkspaceAdmin(WORKSPACE_ID),
      canManageAnyWorkspace: canManageAnyWorkspace()
    };
    return <script type="application/json">{JSON.stringify(seen)}</script>;
  }

  const markup = renderToStaticMarkup(<Probe />);
  const payload = markup
    .replace(/^<script type="application\/json">/, "")
    .replace(/<\/script>$/, "");
  return JSON.parse(payload) as Viewer;
}

describe("useCanAccessAdminEntry", () => {
  it("keeps the admin entry closed to a member holding only custom_game.create", () => {
    const viewer = viewerWith(["custom_game.create"]);

    // Hosting a mix is member-level: it must not imply the admin panel.
    expect(viewer.adminEntry).toBe(false);
    expect(viewer.isWorkspaceAdmin).toBe(false);
    expect(viewer.canManageAnyWorkspace).toBe(false);
  });

  it("opens the admin entry for a real management permission", () => {
    const viewer = viewerWith(["team.update"]);

    expect(viewer.adminEntry).toBe(true);
    expect(viewer.isWorkspaceAdmin).toBe(true);
    expect(viewer.canManageAnyWorkspace).toBe(true);
  });

  it("keeps the admin entry closed to a viewer with no workspace permissions", () => {
    expect(viewerWith([]).adminEntry).toBe(false);
  });
});
