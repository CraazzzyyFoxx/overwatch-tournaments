// @vitest-environment happy-dom
//
// Members at its own top-level route (P3-5). What is pinned here:
//  1. the workspace-admin gate — without `workspace_member.*` the roles are
//     read-only badges and the row menu is gone, rather than controls that
//     fail on submit;
//  2. `?role=` is the filter's only store: it is read on mount and written by
//     the chip, so a shared link lands on the same narrowed list;
//  3. one role change end to end — the cell keeps its inline editor (the one
//     deliberate exception to "details go in a dialog"), and picking a role
//     PATCHes the member's whole role set;
//  4. Add member grants exactly one role — the backend stores a single role.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, useEffect, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import MembersPage from "./page";
import type { WorkspaceMember } from "@/types/workspace.types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getMembers = vi.fn();
const listRolesAll = vi.fn();
const updateMemberRole = vi.fn();
const removeMember = vi.fn();
const addMember = vi.fn();

let permitted = true;

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

const replace = vi.fn((url: string) => {
  window.history.replaceState(null, "", url);
  rerender?.();
});

let rerender: (() => void) | null = null;

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/members",
  useRouter: () => ({ replace, push: replace }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ isSuperuser: false, canAccessAnyPermission: () => permitted })
}));
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (
    selector: (state: {
      currentWorkspaceId: number;
      getCurrentWorkspace: () => { name: string };
    }) => unknown
  ) => selector({ currentWorkspaceId: 1, getCurrentWorkspace: () => ({ name: "Anak" }) })
}));
vi.mock("@/services/rbac.service", () => ({
  rbacService: {
    listRolesAll: (...args: unknown[]) => listRolesAll(...args),
    listUsersAll: () => Promise.resolve([{ id: 7, username: "nova" }])
  }
}));
vi.mock("@/services/workspace.service", () => ({
  default: {
    getMembers: (...args: unknown[]) => getMembers(...args),
    addMember: (...args: unknown[]) => addMember(...args),
    removeMember: (...args: unknown[]) => removeMember(...args),
    updateMemberRole: (...args: unknown[]) => updateMemberRole(...args),
    autofillMemberRoles: vi.fn()
  }
}));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

// `caster` is deliberately custom: the chip lists every scoped role, not the
// five system names the row editor offers.
const ROLES = [
  { id: 3, name: "admin", is_system: true, description: null },
  { id: 4, name: "player", is_system: true, description: null },
  { id: 9, name: "caster", is_system: false, description: "Streams matches" }
];

const MEMBER: WorkspaceMember = {
  id: 1,
  workspace_id: 1,
  auth_user_id: 42,
  username: "vitorio",
  email: "vitorio@example.com",
  rbac_roles: [
    { id: 4, name: "player", is_system: true },
    { id: 9, name: "caster", is_system: false }
  ]
};

const mounted: { root: Root; container: HTMLElement }[] = [];

async function settle(turns = 6, delayMs = 0) {
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
  window.history.replaceState(null, "", `/admin/members${search}`);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mounted.push({ root, container });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <Harness render={() => <MembersPage />} />
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

function commandItem(label: string) {
  return Array.from(document.querySelectorAll('[cmdk-item=""]')).find(
    (item) => item.textContent?.trim().startsWith(label)
  );
}

function lastRoleId(): unknown {
  return (getMembers.mock.calls.at(-1)?.[1] as { role_id?: unknown } | undefined)?.role_id;
}

function lastExcludeRoleIds(): unknown {
  return (getMembers.mock.calls.at(-1)?.[1] as { exclude_role_id?: unknown } | undefined)?.exclude_role_id;
}

beforeEach(() => {
  permitted = true;
  replace.mockClear();
  getMembers.mockReset().mockResolvedValue({
    results: [MEMBER],
    total: 1,
    page: 1,
    per_page: 25
  });
  listRolesAll.mockReset().mockResolvedValue(ROLES);
  updateMemberRole.mockReset().mockResolvedValue(undefined);
  removeMember.mockReset().mockResolvedValue(undefined);
  addMember.mockReset().mockResolvedValue(undefined);
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

describe("admin Members", () => {
  it("shows read-only roles and no row menu without workspace_member grants", async () => {
    permitted = false;
    const container = await mount();

    expect(container.textContent).toContain("player");
    expect(
      container.querySelector('[aria-label="Workspace role for vitorio"]')
    ).toBeNull();
    expect(container.querySelector('[aria-label="Actions for vitorio"]')).toBeNull();
  });

  it("gives a workspace admin the inline editor and the row menu", async () => {
    const container = await mount();

    expect(
      container.querySelector('[aria-label="Workspace role for vitorio"]')
    ).not.toBeNull();
    expect(container.querySelector('[aria-label="Actions for vitorio"]')).not.toBeNull();
  });

  it("reads ?role= on mount", async () => {
    await mount("?role=9");

    expect(lastRoleId()).toBe(9);
  });

  it("writes ?role= when the chip is picked, and refetches", async () => {
    const container = await mount();
    expect(lastRoleId()).toBeNull();

    await click(container.querySelector('[aria-label="Add filter"]'));
    await click(commandItem("Role"));
    await click(commandItem("caster"));

    expect(window.location.search).toContain("role=9");
    expect(lastRoleId()).toBe(9);
  });

  it("reads ?exclude_role= on mount and refetches without those holders", async () => {
    await mount("?exclude_role=9,3");

    expect(lastExcludeRoleIds()).toEqual([9, 3]);
  });

  it("writes ?exclude_role= when the exclude chip is picked", async () => {
    const container = await mount();

    await click(container.querySelector('[aria-label="Add filter"]'));
    await click(commandItem("Exclude role"));
    await click(commandItem("caster"));

    expect(window.location.search).toContain("exclude_role=9");
    expect(lastExcludeRoleIds()).toEqual([9]);
  });

  it("changes a member's system role from the cell, keeping their custom roles", async () => {
    const container = await mount();

    await click(container.querySelector('[aria-label="Workspace role for vitorio"]'));
    await click(
      Array.from(document.querySelectorAll('[role="option"]')).find(
        (option) => option.textContent?.trim() === "Admin"
      )
    );

    expect(updateMemberRole).toHaveBeenCalledWith(1, 42, [3, 9]);
  });

  it("adds a member with the one role picked in the dialog", async () => {
    await mount();
    const button = (label: string, root: ParentNode = document) =>
      Array.from(root.querySelectorAll("button")).find((item) => item.textContent?.trim() === label);

    await click(button("Add member"));
    const dialog = document.querySelector('[role="dialog"]')!;
    await click(button("Select user…", dialog));
    await click(commandItem("nova"));
    const roleLabel = Array.from(dialog.querySelectorAll("label")).find(
      (label) => label.textContent === "Role"
    );
    await click(document.getElementById(roleLabel!.htmlFor));
    await click(
      Array.from(document.querySelectorAll('[role="option"]')).find(
        (option) => option.textContent?.trim() === "Admin"
      )
    );
    await click(button("Add member", dialog));

    expect(addMember).toHaveBeenCalledWith(1, 7, 3);
  });

  it("removes a member through the row menu and the shared confirmation", async () => {
    const container = await mount();

    await click(container.querySelector('[aria-label="Actions for vitorio"]'));
    await click(
      Array.from(document.querySelectorAll('[role="menuitem"]')).find(
        (item) => item.textContent?.trim() === "Remove from workspace"
      )
    );
    expect(document.body.textContent).toContain("loses access to Anak");

    await click(
      Array.from(document.querySelectorAll("button")).find(
        (item) => item.textContent?.trim() === "Remove member"
      )
    );

    expect(removeMember).toHaveBeenCalledWith(1, 42);
  });
});
