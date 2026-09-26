// @vitest-environment happy-dom
//
// The reported bug, end to end: signed in as a *workspace owner*, the player
// identities entry (now `People`) was absent from the admin sidebar —
// `globalOnly` demanded a global `user.read`, which an owner never holds
// (their `admin.*` is workspace-scoped), so the entry was filtered out and the
// route guard answered UnauthorizedState.
//
// This exercises the real composition behind that symptom — profile store ->
// `usePermissions` -> the exact predicates `AdminSidebar` and
// `AdminLayoutClient` build — rather than the route table alone, and pins the
// two halves that must NOT move with it: a workspace grant still buys no write
// on the global identity, and genuinely global surfaces (the stream poller,
// superuser game content) stay out of reach.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The real store hydrates its workspace from a cookie, which no test sets.
// Only `currentWorkspaceId` matters here, so it is pinned outright.
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector?: (state: { currentWorkspaceId: number | null }) => unknown) => {
    const state = { currentWorkspaceId: 7 };
    return selector ? selector(state) : state;
  },
}));

import {
  adminEntryPermissions,
} from "@/lib/auth/admin-permissions";
import {
  getMatchingAdminRoute,
  getVisibleAdminNavigationGroups,
} from "@/components/admin/admin-navigation";
import { usePermissions } from "@/hooks/usePermissions";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import { useWorkspaceStore } from "@/stores/workspace.store";

const WORKSPACE = 7;

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

type Probe = {
  navHrefs: string[];
  canOpenUsersRoute: boolean;
  canCreateIdentity: boolean;
  canUpdateIdentity: boolean;
  canListWorkspaceIdentities: boolean;
};

/** The predicate `AdminSidebar` passes to `getVisibleAdminNavigationGroups`, and
 *  the guard `AdminLayoutClient` runs for the current pathname — verbatim. */
function ProbeComponent({ onReady }: { readonly onReady: (probe: Probe) => void }) {
  const { canAccessAdminRoute, canAccessPermission, hasPermission } = usePermissions();
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);

  const groups = getVisibleAdminNavigationGroups((item) =>
    canAccessAdminRoute({
      permissions: item.permissions,
      workspaceId: item.workspaceAdminVisible ? null : currentWorkspaceId,
      globalOnly: item.globalOnly,
      workspaceAdminVisible: item.workspaceAdminVisible,
      superuserOnly: item.superuserOnly,
    }),
  );

  const route = getMatchingAdminRoute("/admin/people");
  onReady({
    navHrefs: groups.flatMap((group) => group.items.map((item) => item.href)),
    canOpenUsersRoute: route
      ? canAccessAdminRoute({
          permissions: route.permissions,
          workspaceId: route.workspaceAdminVisible ? null : currentWorkspaceId,
          globalOnly: route.globalOnly,
          workspaceAdminVisible: route.workspaceAdminVisible,
          superuserOnly: route.superuserOnly,
        })
      : canAccessAdminRoute({ permissions: adminEntryPermissions, workspaceId: currentWorkspaceId }),
    canCreateIdentity: hasPermission("user.create"),
    canUpdateIdentity: hasPermission("user.update"),
    canListWorkspaceIdentities: canAccessPermission("user.read", currentWorkspaceId),
  });
  return null;
}

async function probe(): Promise<Probe> {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  let captured: Probe | undefined;

  await act(async () => {
    root.render(<ProbeComponent onReady={(value) => (captured = value)} />);
  });
  await act(async () => {
    root.unmount();
  });
  container.remove();

  if (!captured) throw new Error("probe never rendered");
  return captured;
}

describe("a workspace owner's admin navigation", () => {
  beforeEach(() => {
    // What /api/v1/auth/me returns for an owner: no global role, no global
    // permission, one workspace carrying the `owner` role's `admin.*`.
    useAuthProfileStore.setState({
      status: "authenticated",
      user: {
        id: 42,
        username: "owner",
        roles: [],
        permissions: [],
        denies: [],
        isSuperuser: false,
        workspaces: [{ workspace_id: WORKSPACE, slug: "ws", roles: ["owner"], permissions: ["admin.*"] }],
        linkedPlayers: [],
      },
    });
  });

  it("shows People and lets the route open", async () => {
    const { navHrefs, canOpenUsersRoute, canListWorkspaceIdentities } = await probe();

    expect(navHrefs).toContain("/admin/people");
    expect(canOpenUsersRoute).toBe(true);
    expect(canListWorkspaceIdentities).toBe(true);
  });

  it("offers no write on the platform-wide identity", async () => {
    // The page's Create/Rename/Delete affordances hang off these: the backend
    // keeps those on a global grant, so showing them would only produce a 403.
    const { canCreateIdentity, canUpdateIdentity } = await probe();

    expect(canCreateIdentity).toBe(false);
    expect(canUpdateIdentity).toBe(false);
  });

  it("still hides the surfaces that have no workspace dimension", async () => {
    const { navHrefs } = await probe();

    // Superuser-only game content stays out.
    expect(navHrefs).not.toContain("/admin/content/heroes");
    // Collectors is one OR-list entry now, so an owner reaches it — but the
    // stream poller behind it stays global-only at the route level: one
    // poller, one Redis key, no workspace dimension to authorize against.
    expect(getMatchingAdminRoute("/admin/collectors/streams")?.globalOnly).toBe(true);
  });
});
