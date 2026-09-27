// @vitest-environment happy-dom
//
// Access › Roles, driven by a REAL `/api/v1/auth/me` payload instead of a mocked
// `usePermissions`.
//
// `page.behavior.test.tsx` mocks the whole permissions hook, so every gate in
// front of this screen is stubbed out and none of them is actually exercised.
// This file mocks nothing above the network: the real profile store, the real
// `usePermissions`, the real route table, the real Access layout and the real
// page. The profile is the verbatim shape identity-service returns for an
// account that is `owner` of ONE workspace and a plain `host`/`member` of two
// others — the case that was reported broken.
//
// Three gates stand between the URL and the role query, and each one can hide
// the screen without a single request leaving the browser:
//   1. `AdminLayoutClient` -> `canAccessAdminRoute` (the Unauthorized screen),
//   2. the Access layout's tab gate (renders "No Access section is open to
//      you" INSTEAD of children when every tab is hidden),
//   3. the page's own scope fallback, which must land on the workspace the
//      account administers rather than the Global scope its `role.read` does
//      not cover.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";

// The real store fetches its workspaces and hydrates the active one from a
// cookie, so it is the one module stubbed here — with the real `/api/v1/
// workspaces` shape, deliberately NOT owner-first: the page picks
// `adminWorkspaces[0]`, and the store's order is whatever the API returned.
const WORKSPACE_STATE = {
  workspaces: [
    { id: 6, slug: "txao", name: "TXAO" },
    { id: 2, slug: "anakq-dvor", name: "Anak Dvor" },
    { id: 8, slug: "moonrise", name: "Moonrise" }
  ],
  currentWorkspaceId: 8
};
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector?: (state: typeof WORKSPACE_STATE) => unknown) =>
    selector ? selector(WORKSPACE_STATE) : WORKSPACE_STATE
}));

import {
  adminRouteAccessOptions,
  getVisibleAdminNavigationGroups
} from "@/components/admin/admin-navigation";
import { usePermissions } from "@/hooks/usePermissions";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import { useWorkspaceStore } from "@/stores/workspace.store";
import AccessAdminLayout from "../layout";
import RolesPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const OWNED_WORKSPACE = 8;

/** Verbatim `/api/v1/auth/me`, mapped the way `auth-profile.store` maps it. */
const OWNER_PROFILE = {
  id: 26,
  username: "shadow_pulse_dl",
  roles: ["user"],
  permissions: ["user.read", "tournament.read", "team.read", "match.read", "analytics.read"],
  denies: [],
  isSuperuser: false,
  workspaces: [
    {
      workspace_id: 6,
      slug: "txao",
      roles: ["host"],
      // A host's only non-read grants are on `custom_game`, which is
      // deliberately NOT an admin-panel resource.
      permissions: [
        "workspace.read",
        "tournament.read",
        "custom_game.read",
        "custom_game.create",
        "custom_game.update",
        "custom_game.delete"
      ]
    },
    { workspace_id: OWNED_WORKSPACE, slug: "moonrise", roles: ["owner"], permissions: ["admin.*"] },
    {
      workspace_id: 2,
      slug: "anakq-dvor",
      roles: ["member"],
      permissions: ["workspace.read", "tournament.read", "custom_game.read"]
    }
  ],
  linkedPlayers: []
};

const listRolesAll = vi.fn();
const listPermissionsAll = vi.fn();

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

vi.mock("@/services/rbac.service", () => ({
  rbacService: {
    listRolesAll: (...args: unknown[]) => listRolesAll(...args),
    listPermissionsAll: (...args: unknown[]) => listPermissionsAll(...args),
    getRole: vi.fn(),
    createRole: vi.fn(),
    updateRole: vi.fn(),
    deleteRole: vi.fn()
  }
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), apiError: vi.fn() }
}));

vi.mock("next/navigation", () => ({
  usePathname: () => window.location.pathname,
  useRouter: () => ({
    push: (url: string) => window.history.replaceState(null, "", url),
    replace: (url: string) => window.history.replaceState(null, "", url)
  }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  )
}));

const mounted: { root: Root; container: HTMLElement }[] = [];

async function settle(turns = 8, delayMs = 0) {
  for (let turn = 0; turn < turns; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, delayMs);
      await promise;
    });
  }
}

/** The exact predicate `AdminLayoutClient` runs before rendering anything. */
let routeGate: boolean | null = null;
let navHrefs: string[] = [];

type Probed = { routeGate: boolean; navHrefs: string[] };

function Probe({ onReady }: Readonly<{ onReady: (probe: Probed) => void }>) {
  const { canAccessAdminRoute } = usePermissions();
  const currentWorkspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  onReady({
    routeGate: canAccessAdminRoute(
      adminRouteAccessOptions("/admin/access/roles", currentWorkspaceId)
    ),
    navHrefs: getVisibleAdminNavigationGroups((item) =>
      canAccessAdminRoute({
        permissions: item.permissions,
        workspaceId: item.workspaceAdminVisible ? null : currentWorkspaceId,
        globalOnly: item.globalOnly,
        workspaceAdminVisible: item.workspaceAdminVisible,
        superuserOnly: item.superuserOnly
      })
    ).flatMap((group) => group.items.map((item) => item.href))
  });
  return null;
}

async function mount() {
  window.history.replaceState(null, "", "/admin/access/roles");
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mounted.push({ root, container });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <TooltipProvider>
          <Probe
            onReady={(probe) => {
              routeGate = probe.routeGate;
              navHrefs = probe.navHrefs;
            }}
          />
          <AccessAdminLayout>
            <RolesPage />
          </AccessAdminLayout>
        </TooltipProvider>
      </QueryClientProvider>
    );
  });
  await settle();
  return container;
}

beforeEach(() => {
  routeGate = null;
  navHrefs = [];
  listRolesAll.mockReset().mockResolvedValue([]);
  listPermissionsAll.mockReset().mockResolvedValue([]);
  useAuthProfileStore.setState({ status: "authenticated", user: OWNER_PROFILE });
  window.matchMedia = ((query: string) => ({
    matches: query.includes("min-width"),
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false
  })) as unknown as typeof window.matchMedia;
  document.body.innerHTML = "";
});

afterEach(async () => {
  await act(async () => {
    for (const { root, container } of mounted.splice(0)) {
      root.unmount();
      container.remove();
    }
  });
  useAuthProfileStore.setState({ status: "idle", user: undefined });
  document.body.innerHTML = "";
});

describe("Access › Roles · a workspace owner with no global RBAC grant", () => {
  it("passes the admin route gate, so the panel never answers Unauthorized", async () => {
    await mount();

    expect(routeGate).toBe(true);
    expect(navHrefs).toContain("/admin/access");
  });

  it("keeps the Roles tab open and renders the page, not the empty-hub card", async () => {
    const container = await mount();

    const tabs = Array.from(
      document.querySelectorAll("nav[aria-label='Access sections'] a")
    ).map((link) => link.getAttribute("href"));
    expect(tabs).toContain("/admin/access/roles");
    expect(container.textContent).not.toContain("No Access section is open to you");
  });

  it("scopes the role query to the owned workspace, never the Global scope", async () => {
    await mount();

    expect(listRolesAll).toHaveBeenCalled();
    // `workspace_id: null` here is the Global scope, which this account's
    // `role.read` does not cover — the request would come back 403.
    expect(listRolesAll.mock.calls.at(-1)?.[0]).toEqual({ workspace_id: OWNED_WORKSPACE });
  });

  it("reaches the empty-scope state, not the load-failure card", async () => {
    const container = await mount();

    // The scope resolved to something the account may read, so the query
    // settled: the screen shows "no roles here yet", never the error card.
    expect(container.textContent).not.toContain("Could not load the roles");
    expect(container.textContent).toContain("No roles in this scope");
  });
});
