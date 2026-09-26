// @vitest-environment happy-dom
//
// Route × role table for every destination in the admin IA route map.
//
// The risk this closes: the guard is a prefix table maintained by hand next to
// the menu, so a rewritten prefix can silently widen a gate — a superuser-only
// screen falling through to the `/admin` catch-all is a real leak, and it is
// invisible in a structural test that only reads the row it expects to find.
// This drives the REAL predicate (`usePermissions().canAccessAdminRoute`, the
// verbatim call `AdminLayoutClient` makes) against four profiles.
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
  adminRouteAccessOptions,
  getMatchingAdminRoute,
} from "@/components/admin/admin-navigation";
import { type AppPermission, usePermissions } from "@/hooks/usePermissions";
import { type AuthProfile, useAuthProfileStore } from "@/stores/auth-profile.store";
import { useWorkspaceStore } from "@/stores/workspace.store";

const WORKSPACE = 7;

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

function profile(overrides: Partial<AuthProfile>): AuthProfile {
  return {
    id: 1,
    username: "probe",
    roles: [],
    permissions: [],
    denies: [],
    isSuperuser: false,
    workspaces: [],
    linkedPlayers: [],
    ...overrides,
  };
}

const PROFILES: Record<string, AuthProfile> = {
  superuser: profile({ username: "root", isSuperuser: true }),
  /** Workspace owner: no global grant at all, `admin.*` inside one workspace. */
  owner: profile({
    username: "owner",
    workspaces: [
      { workspace_id: WORKSPACE, slug: "ws", roles: ["owner"], permissions: ["admin.*"] },
    ],
  }),
  /**
   * A global moderator: the panel role, no workspace membership.
   *
   * Read-only grants alone open nothing — `hasAdminPanelAccessForProfile`
   * needs a panel role, a non-`.read` permission or a managed workspace — so
   * the role is what makes this profile interesting. Note the existing
   * semantics it pins: a panel role satisfies every PERMISSION gate
   * (`canAccessAnyPermissionForProfile` short-circuits on it), while
   * workspace-scoped and superuser gates still hold it out.
   */
  moderator: profile({
    username: "mod",
    roles: ["moderator"],
    permissions: ["tournament.read", "match.read"] as AppPermission[],
  }),
  /** Signed in, nothing granted: the admin panel must be closed end to end. */
  outsider: profile({ username: "outsider" }),
};

/** The guard `AdminLayoutClient` runs for a pathname — verbatim. */
function Probe({
  paths,
  onReady,
}: {
  readonly paths: string[];
  readonly onReady: (result: Record<string, boolean>) => void;
}) {
  const { canAccessAdminRoute } = usePermissions();
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);

  const result: Record<string, boolean> = {};
  for (const path of paths) {
    result[path] = canAccessAdminRoute(adminRouteAccessOptions(path, currentWorkspaceId));
  }
  onReady(result);
  return null;
}

async function access(role: keyof typeof PROFILES, paths: string[]) {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  useAuthProfileStore.setState({ status: "authenticated", user: PROFILES[role] });

  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  let captured: Record<string, boolean> | undefined;

  await act(async () => {
    root.render(<Probe paths={paths} onReady={(value) => (captured = value)} />);
  });
  await act(async () => {
    root.unmount();
  });
  container.remove();

  if (!captured) throw new Error("probe never rendered");
  return captured;
}

/** Every destination in §1.1, plus the old paths still standing. */
const ROUTES = {
  hub: [
    "/admin",
    "/admin/tournaments",
    "/admin/tournaments/new",
    "/admin/tournaments/14/overview",
    "/admin/tournaments/14/registration/entries",
    "/admin/tournaments/14/teams/roster",
    "/admin/tournaments/14/teams/draft",
    "/admin/tournaments/14/bracket",
    "/admin/tournaments/14/matches/encounters",
    "/admin/tournaments/14/matches/standings",
    "/admin/tournaments/14/matches/reports",
    "/admin/tournaments/14/matches/parsed",
    "/admin/tournaments/14/matches/logs",
    "/admin/tournaments/14/settings/general",
    "/admin/tournaments/14/settings/pre-game",
    "/admin/tournaments/14/settings/danger",
  ],
  data: [
    "/admin/people",
    "/admin/people/42",
    "/admin/teams",
    "/admin/teams/9",
    "/admin/matches",
    "/admin/achievements",
    "/admin/achievements/3",
    "/admin/audit",
  ],
  workspace: [
    "/admin/settings/general",
    "/admin/settings/branding",
    "/admin/settings/visibility",
    "/admin/settings/domain",
    "/admin/settings/discord",
    "/admin/settings/divisions",
    "/admin/settings/divisions/v/4",
    "/admin/settings/divisions/import",
    "/admin/settings/subscriptions",
    "/admin/members",
    "/admin/workspaces",
    "/admin/workspaces/8/general",
  ],
  /**
   * The hub landing: the union gate, open to anyone with any Access section.
   * It must stay open to a workspace admin — pointing the sidebar entry at
   * global-only Accounts is what walled them out of the whole block.
   */
  accessHub: ["/admin/access"],
  superuserOnly: [
    "/admin/content/heroes",
    "/admin/content/maps",
    "/admin/content/gamemodes",
    "/admin/content/unresolved",
    "/admin/access/sessions",
  ],
  globalOnly: [
    "/admin/collectors/streams",
    "/admin/access/accounts",
    "/admin/access/oauth",
    "/admin/access/permissions",
  ],
};

const EVERY_ROUTE = Object.values(ROUTES).flat();

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("route × role access", () => {
  it("opens every route in the map for a superuser", async () => {
    const granted = await access("superuser", EVERY_ROUTE);

    for (const [path, allowed] of Object.entries(granted)) {
      expect(allowed, path).toBe(true);
    }
  });

  it("closes every route in the map for a signed-in outsider", async () => {
    const granted = await access("outsider", EVERY_ROUTE);

    for (const [path, allowed] of Object.entries(granted)) {
      expect(allowed, path).toBe(false);
    }
  });

  it("opens the hub, the data browsers and the workspace hub for a workspace owner", async () => {
    const granted = await access("owner", [
      ...ROUTES.hub,
      ...ROUTES.data,
      ...ROUTES.workspace,
      ...ROUTES.accessHub,
    ]);

    for (const [path, allowed] of Object.entries(granted)) {
      expect(allowed, path).toBe(true);
    }
  });

  it("keeps superuser-only and global-only screens shut for a workspace owner", async () => {
    const granted = await access("owner", [...ROUTES.superuserOnly, ...ROUTES.globalOnly]);

    for (const [path, allowed] of Object.entries(granted)) {
      expect(allowed, path).toBe(false);
    }
  });

  it("lets a global moderator into the hub, the browsers and the collectors", async () => {
    const granted = await access("moderator", [
      "/admin",
      ...ROUTES.hub,
      ...ROUTES.data,
      ...ROUTES.accessHub,
      "/admin/collectors/rank",
      "/admin/collectors/subscriptions",
    ]);

    for (const [path, allowed] of Object.entries(granted)) {
      expect(allowed, path).toBe(true);
    }
  });

  it("keeps a global moderator out of workspace configuration and superuser screens", async () => {
    // Workspace configuration needs a managed workspace, which a global-only
    // moderator does not have; game content and sessions need superuser.
    const granted = await access("moderator", [
      ...ROUTES.workspace,
      ...ROUTES.superuserOnly,
    ]);

    for (const [path, allowed] of Object.entries(granted)) {
      expect(allowed, path).toBe(false);
    }
  });

  it("never lets a route fall through to the /admin catch-all", async () => {
    // The catch-all's gate is `adminEntryPermissions`, i.e. "anything at all",
    // which is how a narrow screen quietly becomes readable by every admin.
    for (const path of EVERY_ROUTE) {
      if (path === "/admin") continue;
      expect(getMatchingAdminRoute(path)?.prefix, path).not.toBe("/admin");
    }
  });
});
