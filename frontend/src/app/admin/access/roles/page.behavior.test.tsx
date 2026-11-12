// @vitest-environment happy-dom
//
// Access › Roles — the master-detail editor that replaced the 1440px-wide
// permission-matrix dialog. What is pinned here:
//  1. the per-tab gate: Roles is `workspaceAdminVisible`, so a workspace admin
//     with no global RBAC grant still gets this tab while the global-only
//     sections stay hidden;
//  2. `?role=` IS the selection — no param shows the empty detail, picking a
//     role PUSHES a linkable URL (a `replace` would break `MasterDetail`'s
//     narrow-viewport Back), and a deep link opens that role's editor;
//  3. the scope select lives in the URL and re-scopes the role query;
//  4. one permission toggle end to end through the shared `PermissionPicker`:
//     checking a permission chip dirties the `SaveBar`, and saving PATCHes the
//     role with the resolved permission ids.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, useEffect, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@craazzzyyfoxx/admin-kit/ui/tooltip";
import AccessAdminLayout from "../layout";
import RolesPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const listRoles = vi.fn();
const getRole = vi.fn();
const createRole = vi.fn();
const updateRole = vi.fn();
const deleteRole = vi.fn();
const listPermissions = vi.fn();

let globalPermissions: string[] = [
  "role.read",
  "role.create",
  "role.update",
  "role.delete",
  "permission.read"
];
let superuser = false;
let workspaceAdmin = false;

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    isLoaded: true,
    isSuperuser: superuser,
    hasPermission: (permission: string) => superuser || globalPermissions.includes(permission),
    hasAnyPermission: (permissions: string[]) =>
      superuser || permissions.some((permission) => globalPermissions.includes(permission)),
    hasAnyWorkspacePermission: () => false,
    canManageAnyWorkspace: () => superuser || workspaceAdmin,
    canAccessPermission: (permission: string, workspaceId?: number | null) =>
      workspaceId == null
        ? superuser || globalPermissions.includes(permission)
        : superuser || workspaceAdmin || globalPermissions.includes(permission),
    canAccessAnyPermission: (permissions: string[], workspaceId?: number | null) =>
      workspaceId == null
        ? superuser || permissions.some((permission) => globalPermissions.includes(permission))
        : superuser ||
          workspaceAdmin ||
          permissions.some((permission) => globalPermissions.includes(permission))
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

vi.mock("@/services/rbac.service", () => ({
  rbacService: {
    listRolesAll: (...args: unknown[]) => listRoles(...args),
    getRole: (...args: unknown[]) => getRole(...args),
    createRole: (...args: unknown[]) => createRole(...args),
    updateRole: (...args: unknown[]) => updateRole(...args),
    deleteRole: (...args: unknown[]) => deleteRole(...args),
    listPermissionsAll: (...args: unknown[]) => listPermissions(...args)
  }
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), apiError: vi.fn() }
}));

let rerender: (() => void) | null = null;

const navigate = (url: string) => {
  window.history.replaceState(null, "", url);
  rerender?.();
};
// Deliberately separate spies: `MasterDetail`'s narrow-viewport "Back to list"
// is `history.back()`, which only returns to the list if the selection was
// PUSHED, so the test has to be able to tell push from replace.
const push = vi.fn(navigate);
const replace = vi.fn(navigate);

vi.mock("next/navigation", () => ({
  usePathname: () => window.location.pathname,
  useRouter: () => ({ push, replace }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    prefetch: _prefetch,
    ...rest
  }: {
    href: string;
    children: ReactNode;
    prefetch?: boolean | null;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  )
}));

const CASTER = {
  id: 12,
  name: "caster",
  description: "Runs the broadcast",
  is_system: false,
  workspace_id: null,
  created_at: "2026-01-01"
};

const OWNER = {
  id: 1,
  name: "owner",
  description: "Everything",
  is_system: true,
  workspace_id: null,
  created_at: "2026-01-01"
};

const PERMISSIONS = [
  {
    id: 101,
    name: "match.read",
    resource: "match",
    action: "read",
    description: null,
    created_at: "2026-01-01"
  },
  {
    id: 102,
    name: "match.update",
    resource: "match",
    action: "update",
    description: null,
    created_at: "2026-01-01"
  },
  {
    id: 103,
    name: "admin.*",
    resource: "admin",
    action: "*",
    description: "Everything",
    created_at: "2026-01-01"
  }
];

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
  window.history.replaceState(null, "", `/admin/access/roles${search}`);
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
                <RolesPage />
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

function button(text: string) {
  return Array.from(document.querySelectorAll("button")).find(
    (element) => element.textContent?.trim() === text
  );
}

function option(label: string) {
  return Array.from(document.querySelectorAll('[role="option"]')).find(
    (item) => item.textContent?.trim() === label
  );
}

function tabHrefs() {
  return Array.from(document.querySelectorAll("nav[aria-label='Access sections'] a")).map((link) =>
    link.getAttribute("href")
  );
}

function lastRolesScope(): unknown {
  return (listRoles.mock.calls.at(-1)?.[0] as { workspace_id?: unknown } | undefined)?.workspace_id;
}

beforeEach(() => {
  globalPermissions = [
    "role.read",
    "role.create",
    "role.update",
    "role.delete",
    "permission.read"
  ];
  superuser = false;
  workspaceAdmin = false;
  push.mockClear();
  replace.mockClear();
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
  listRoles.mockReset().mockResolvedValue([OWNER, CASTER]);
  getRole.mockReset().mockResolvedValue({ ...CASTER, permissions: [PERMISSIONS[0]] });
  createRole.mockReset().mockResolvedValue({ ...CASTER, id: 33, name: "stats-bot" });
  updateRole.mockReset().mockResolvedValue(CASTER);
  deleteRole.mockReset().mockResolvedValue(undefined);
  listPermissions.mockReset().mockResolvedValue(PERMISSIONS);
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

describe("Access › Roles · per-tab gate", () => {
  it("stays open to a workspace admin with no global RBAC grant", async () => {
    globalPermissions = [];
    workspaceAdmin = true;
    await mount();

    expect(tabHrefs()).toEqual(["/admin/access/roles", "/admin/access/api-keys"]);
    // With no global `role.read`, the scope falls back to the workspace this
    // account administers rather than an empty Global list.
    await waitFor(() => lastRolesScope() === 3, "the workspace-scoped role query");
  });

  it("hides Create role without role.create in the scope", async () => {
    globalPermissions = ["role.read", "permission.read"];
    const container = await mount();
    await waitFor(() => container.textContent?.includes("caster"), "the role list");

    expect(button("Create role")).toBeUndefined();
  });
});

describe("Access › Roles · ?role= is the selection", () => {
  it("shows the empty detail until a role is selected", async () => {
    const container = await mount();
    await waitFor(() => container.textContent?.includes("caster"), "the role list");

    expect(container.textContent).toContain("No role selected");
    expect(getRole).not.toHaveBeenCalled();
  });

  it("pushes ?role= when a role is picked", async () => {
    const container = await mount();
    const row = await waitFor(
      () => Array.from(container.querySelectorAll("button")).find(
        (element) => element.textContent?.includes("caster")
      ),
      "the caster row"
    );

    await click(row);

    expect(push).toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
    expect(new URLSearchParams(window.location.search).get("role")).toBe("12");
  });

  it("opens the editor straight from a deep link", async () => {
    const container = await mount("?role=12");

    await waitFor(() => container.textContent?.includes("Runs the broadcast"), "the editor");
    expect(getRole).toHaveBeenCalledWith(12);
  });

  it("re-scopes the role query from the scope select", async () => {
    const container = await mount();
    await waitFor(() => container.textContent?.includes("caster"), "the role list");

    await click(container.querySelector('button[role="combobox"][aria-label="Scope"]'));
    await click(await waitFor(() => option("Anak"), "the workspace option"));

    expect(new URLSearchParams(window.location.search).get("scope")).toBe("3");
    await waitFor(() => lastRolesScope() === 3, "the workspace-scoped role query");
  });
});

describe("Access › Roles · one permission toggle", () => {
  it("dirties the SaveBar and PATCHes the resolved permission ids", async () => {
    const container = await mount("?role=12");
    const box = await waitFor(
      () => document.querySelector('[aria-label="Toggle match.update"]'),
      "the match.update cell"
    );

    // The saved role holds match.read only, so nothing is dirty yet.
    expect(container.querySelector('[aria-label="Unsaved changes"]')).toBeNull();

    await click(box);
    await waitFor(
      () => container.querySelector('[aria-label="Unsaved changes"]'),
      "the save bar"
    );
    await click(button("Save role"));

    expect(updateRole).toHaveBeenCalledWith(12, {
      name: "caster",
      description: "Runs the broadcast",
      permission_ids: [101, 102]
    });
  });

  it("locks the rows a held wildcard already covers", async () => {
    getRole.mockResolvedValue({ ...CASTER, permissions: [PERMISSIONS[2]] });
    await mount("?role=12");

    const box = await waitFor(
      () => document.querySelector('[aria-label="Toggle match.read"]'),
      "the match.read cell"
    );
    // `admin.*` already grants it, so the individual box would be a no-op: it
    // reads as checked and is not operable.
    expect(box.getAttribute("data-state")).toBe("checked");
    expect(box.hasAttribute("disabled")).toBe(true);
  });

  it("keeps a system role read-only", async () => {
    getRole.mockResolvedValue({ ...OWNER, permissions: PERMISSIONS });
    const container = await mount("?role=1");

    await waitFor(() => container.textContent?.includes("cannot be edited"), "the editor");
    const box = await waitFor(
      () => document.querySelector('[aria-label="Toggle match.update"]'),
      "the match.update cell"
    );
    expect(box.hasAttribute("disabled")).toBe(true);
  });
});

describe("Access › Roles · unsaved draft", () => {
  it("intercepts a role switch that would throw the draft away", async () => {
    const container = await mount("?role=12");
    await click(
      await waitFor(
        () => document.querySelector('[aria-label="Toggle match.update"]'),
        "the match.update cell"
      )
    );
    await waitFor(() => container.querySelector('[aria-label="Unsaved changes"]'), "the save bar");

    // The list is buttons (the selection has to be PUSHED), so `SaveBar`'s own
    // anchor-click guard cannot see this: the screen intercepts it instead.
    await click(
      Array.from(container.querySelectorAll("button")).find((element) =>
        element.textContent?.includes("owner")
      )
    );

    expect(new URLSearchParams(window.location.search).get("role")).toBe("12");
    expect(document.body.textContent).toContain("Discard unsaved changes?");

    await click(await waitFor(() => button("Discard changes"), "the discard button"));

    expect(new URLSearchParams(window.location.search).get("role")).toBe("1");
  });
});

describe("Access › Roles · deletion", () => {
  it("goes through the screen's single ConfirmDialog", async () => {
    const container = await mount("?role=12");
    await waitFor(() => container.textContent?.includes("Runs the broadcast"), "the editor");

    await click(container.querySelector('button[aria-label="Actions for role caster"]'));
    await click(
      await waitFor(
        () =>
          Array.from(document.querySelectorAll('[role="menuitem"]')).find(
            (item) => item.textContent?.trim() === "Delete role"
          ),
        "the delete action"
      )
    );
    await click(await waitFor(() => button("Delete role"), "the confirm button"));

    expect(deleteRole).toHaveBeenCalledWith(12);
  });
});
