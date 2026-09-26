// @vitest-environment happy-dom
//
// Access › Accounts — the auth-account browser that replaced
// /admin/access/users. What is pinned here:
//  1. the per-tab gate: the tab bar and the route table agree, so a workspace
//     admin without the global `auth_user.read` sees Roles and API keys but
//     NOT Accounts, and Sessions stays superuser-only;
//  2. chips are the URL: the Status chip narrows the request and a deep link
//     restores it, rather than living in component state;
//  3. one permission toggle end to end, through the shared `PermissionPicker`:
//     checking a capability in the inspector's restrictions panel POSTs a deny;
//  4. six columns do not fit a phone, so rows render as cards below `md`.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, useEffect, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import AccessAdminLayout from "../layout";
import AccountsPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const listUsers = vi.fn();
const getUser = vi.fn();
const listRolesAll = vi.fn();
const listOAuthConnections = vi.fn();
const listPermissionsAll = vi.fn();
const getUserDenies = vi.fn();
const addUserDeny = vi.fn();
const removeUserDeny = vi.fn();
const deleteUser = vi.fn();

/** The permissions the mocked profile holds globally. */
let globalPermissions: string[] = [
  "auth_user.read",
  "auth_user.update",
  "role.read",
  "role.update",
  "user.read",
  "permission.read"
];
let superuser = false;
let workspaceAdmin = false;

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key
}));
vi.mock("@/lib/datetime/client", () => ({
  useFormatter: () => ({ dateTime: (value: Date) => value.toISOString().slice(0, 10) })
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    isLoaded: true,
    isSuperuser: superuser,
    hasPermission: (permission: string) => superuser || globalPermissions.includes(permission),
    hasAnyPermission: (permissions: string[]) =>
      superuser || permissions.some((permission) => globalPermissions.includes(permission)),
    hasAnyWorkspacePermission: () => false,
    canManageAnyWorkspace: () => superuser || workspaceAdmin,
    canAccessPermission: (permission: string) =>
      superuser || globalPermissions.includes(permission)
  })
}));

vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (
    selector: (state: {
      workspaces: { id: number; name: string }[];
      currentWorkspaceId: number | null;
    }) => unknown
  ) => selector({ workspaces: [{ id: 3, name: "Anak" }], currentWorkspaceId: 3 })
}));

vi.mock("@/stores/auth-profile.store", () => ({
  useAuthProfileStore: (selector: (state: { user: { id: number } | null }) => unknown) =>
    selector({ user: { id: 1 } })
}));

vi.mock("@/services/rbac.service", () => ({
  rbacService: {
    listUsers: (...args: unknown[]) => listUsers(...args),
    getUser: (...args: unknown[]) => getUser(...args),
    listRolesAll: (...args: unknown[]) => listRolesAll(...args),
    listOAuthConnections: (...args: unknown[]) => listOAuthConnections(...args),
    listPermissionsAll: (...args: unknown[]) => listPermissionsAll(...args),
    getUserDenies: (...args: unknown[]) => getUserDenies(...args),
    addUserDeny: (...args: unknown[]) => addUserDeny(...args),
    removeUserDeny: (...args: unknown[]) => removeUserDeny(...args),
    deleteUser: (...args: unknown[]) => deleteUser(...args),
    assignRole: vi.fn(),
    removeRole: vi.fn(),
    assignLinkedPlayer: vi.fn(),
    removeLinkedPlayer: vi.fn()
  }
}));

// Its own query stack is irrelevant here; the panel around it is what matters.
vi.mock("@/components/admin/UserSearchCombobox", () => ({
  UserSearchCombobox: () => null
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), apiError: vi.fn() }
}));

let rerender: (() => void) | null = null;

const replace = vi.fn((url: string) => {
  window.history.replaceState(null, "", url);
  rerender?.();
});

vi.mock("next/navigation", () => ({
  usePathname: () => window.location.pathname,
  useRouter: () => ({ replace, push: replace }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  )
}));

const ACCOUNT = {
  id: 90,
  email: "nnniik@example.com",
  username: "nnniik",
  is_active: true,
  is_superuser: false,
  is_verified: true,
  linked_players: [
    { player_id: 11, player_name: "nnniik#2515", is_primary: true, linked_at: "2026-01-01" }
  ],
  roles: [{ id: 5, name: "caster", description: "Runs the broadcast", is_system: false }],
  created_at: "2026-01-01T00:00:00Z"
};

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

function Harness({ render }: Readonly<{ render: () => ReactNode }>) {
  const [, force] = useState(0);
  // Published from an effect, not during render: writing a module-scope binding
  // while rendering is a side effect the react-compiler rules reject.
  useEffect(() => {
    rerender = () => force((value) => value + 1);
  }, []);
  return <>{render()}</>;
}

async function mount(search = "") {
  window.history.replaceState(null, "", `/admin/access/accounts${search}`);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mounted.push({ root, container });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <TooltipProvider>
          <Harness
            render={() => (
              <AccessAdminLayout>
                <AccountsPage />
              </AccessAdminLayout>
            )}
          />
        </TooltipProvider>
      </QueryClientProvider>
    );
  });
  await settle();
  return container;
}

async function click(element: Element | null | undefined) {
  expect(element).toBeTruthy();
  await act(async () => {
    (element as HTMLElement).dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    element!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await settle(3);
}

async function waitFor<T>(read: () => T | null | undefined | false, what: string): Promise<T> {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const value = read();
    if (value) return value as T;
    await settle(1, 25);
  }
  throw new Error(`timed out waiting for ${what}`);
}

function commandItem(label: string) {
  return Array.from(document.querySelectorAll('[cmdk-item=""]')).find((item) =>
    item.textContent?.trim().startsWith(label)
  );
}

function tabHrefs() {
  return Array.from(document.querySelectorAll("nav[aria-label='Access sections'] a")).map((link) =>
    link.getAttribute("href")
  );
}

function lastListUsersArgs(): Record<string, unknown> {
  return (listUsers.mock.calls.at(-1)?.[0] ?? {}) as Record<string, unknown>;
}

function setViewportWidth(width: number) {
  Object.defineProperty(window, "innerWidth", { value: width, configurable: true });
  window.matchMedia = ((query: string) => ({
    // Both breakpoints the screen reads answer from the same width: the table
    // becomes cards below `md`, the inspector becomes a sheet below `lg`.
    matches: query.includes("max-width") ? width < 768 : width >= 1024,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false
  })) as unknown as typeof window.matchMedia;
}

beforeEach(() => {
  globalPermissions = [
    "auth_user.read",
    "auth_user.update",
    "role.read",
    "role.update",
    "user.read",
    "permission.read"
  ];
  superuser = false;
  workspaceAdmin = false;
  replace.mockClear();
  setViewportWidth(1280);
  listUsers.mockReset().mockResolvedValue({
    results: [ACCOUNT],
    total: 1,
    page: 1,
    per_page: 15
  });
  getUser.mockReset().mockResolvedValue({ ...ACCOUNT, effective_permissions: ["match.read"] });
  listRolesAll
    .mockReset()
    .mockResolvedValue([
      { id: 5, name: "caster", description: null, is_system: false, created_at: "2026-01-01" }
    ]);
  listOAuthConnections.mockReset().mockResolvedValue({ results: [], total: 0, page: 1, per_page: -1 });
  listPermissionsAll.mockReset().mockResolvedValue([
    {
      id: 71,
      name: "account.avatar",
      resource: "account",
      action: "avatar",
      description: "Change own avatar",
      created_at: "2026-01-01"
    },
    {
      id: 72,
      name: "account.social",
      resource: "account",
      action: "social",
      description: "Manage own linked accounts",
      created_at: "2026-01-01"
    },
    {
      id: 73,
      name: "registration.self_register",
      resource: "registration",
      action: "self_register",
      description: "Self-register for a tournament",
      created_at: "2026-01-01"
    },
    {
      id: 74,
      name: "workspace.self_create",
      resource: "workspace",
      action: "self_create",
      description: "Create one's own workspace",
      created_at: "2026-01-01"
    }
  ]);
  getUserDenies.mockReset().mockResolvedValue([]);
  addUserDeny.mockReset().mockResolvedValue([
    { permission_id: 71, name: "account.avatar", resource: "account", action: "avatar" }
  ]);
  removeUserDeny.mockReset().mockResolvedValue([]);
  deleteUser.mockReset().mockResolvedValue(undefined);
  document.body.innerHTML = "";
});

afterEach(async () => {
  await act(async () => {
    for (const { root, container } of mounted.splice(0)) {
      root.unmount();
      container.remove();
    }
  });
  document.body.innerHTML = "";
});

describe("Access › Accounts · per-tab gate", () => {
  it("shows the sections a global RBAC reader holds, and no others", async () => {
    await mount();

    // API keys wants `team.create` or workspace admin, Sessions wants
    // superuser; this profile is neither, so neither tab is offered.
    expect(tabHrefs()).toEqual([
      "/admin/access/accounts",
      "/admin/access/roles",
      "/admin/access/permissions",
      "/admin/access/oauth"
    ]);
  });

  it("hides Accounts, Permissions and OAuth from a workspace admin with no global grant", async () => {
    globalPermissions = [];
    workspaceAdmin = true;
    await mount();

    // Roles and API keys are `workspaceAdminVisible` in the route table; the
    // three global-only reads are not, and Sessions needs superuser.
    expect(tabHrefs()).toEqual(["/admin/access/roles", "/admin/access/api-keys"]);
  });

  it("opens Sessions only for a superuser", async () => {
    superuser = true;
    await mount();

    expect(tabHrefs()).toContain("/admin/access/sessions");
  });
});

describe("Access › Accounts · chips are the URL", () => {
  it("writes the Status chip to the URL and narrows the request by it", async () => {
    const container = await mount();
    await waitFor(() => container.textContent?.includes("nnniik@example.com"), "the account row");
    expect(lastListUsersArgs().is_active).toBeUndefined();

    await click(container.querySelector('button[aria-label="Add filter"]'));
    await click(await waitFor(() => commandItem("Status"), "the Status filter"));
    await click(await waitFor(() => commandItem("Inactive"), "the Inactive option"));

    expect(new URLSearchParams(window.location.search).get("status")).toBe("inactive");
    await waitFor(() => lastListUsersArgs().is_active === false, "the narrowed request");
  });

  it("restores a chip from a deep link", async () => {
    const container = await mount("?superuser=1");
    await waitFor(() => lastListUsersArgs().is_superuser === true, "the narrowed request");

    expect(
      container.querySelector('button[aria-label="Remove filter Superusers only"]')
    ).not.toBeNull();
  });

  it("opens the inspector for the clicked row and writes ?id=", async () => {
    const container = await mount();
    const row = await waitFor(
      () => container.querySelector("tbody tr[tabindex]"),
      "the first data row"
    );

    await click(row);

    expect(new URLSearchParams(window.location.search).get("id")).toBe("90");
    const inspector = await waitFor(
      () => document.querySelector('aside[aria-label="Row inspector"], [role="dialog"]'),
      "the inspector"
    );
    expect(inspector.textContent).toContain("caster");
    expect(
      Array.from(inspector.querySelectorAll("a")).some(
        (link) => link.getAttribute("href") === "/admin/people/11"
      )
    ).toBe(true);
  });
});

describe("Access › Accounts · one permission toggle", () => {
  it("denies a capability through the shared PermissionPicker", async () => {
    await mount("?id=90");
    const box = await waitFor(
      () => document.querySelector('[aria-label="Toggle account.avatar"]'),
      "the restrictions picker"
    );

    await click(box);

    expect(addUserDeny).toHaveBeenCalledWith(90, 71, null);
  });

  // The whole point of a restrictable capability is that this screen can take
  // it away; one that the backend gates but the picker never lists is
  // unrevokable in practice.
  it("can revoke workspace creation globally", async () => {
    await mount("?id=90");
    const box = await waitFor(
      () => document.querySelector('[aria-label="Toggle workspace.self_create"]'),
      "the workspace.self_create row"
    );

    await click(box);

    expect(addUserDeny).toHaveBeenCalledWith(90, 74, null);
  });

  it("offers no restriction control without role.update", async () => {
    globalPermissions = ["auth_user.read", "user.read", "role.read"];
    await mount("?id=90");
    const box = await waitFor(
      () => document.querySelector('[aria-label="Toggle account.avatar"]'),
      "the restrictions picker"
    );

    expect(box.hasAttribute("disabled")).toBe(true);
  });
});

describe("Access › Accounts · narrow viewport", () => {
  it("renders rows as cards below md, where five columns do not fit", async () => {
    setViewportWidth(375);
    const container = await mount();
    const cards = await waitFor(() => {
      const list = container.querySelectorAll("ul[aria-label='Rows'] > li");
      return list.length > 0 ? list : null;
    }, "the mobile cards");

    expect(container.querySelector("table")).toBeNull();
    expect(cards[0].textContent).toContain("nnniik@example.com");
    // The card is chosen, not the first three columns: on a phone the status
    // and the roles are what say whether this login can do anything.
    expect(cards[0].textContent).toContain("Active");
    expect(cards[0].textContent).toContain("caster");
  });
});
