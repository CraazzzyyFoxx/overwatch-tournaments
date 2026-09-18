// @vitest-environment happy-dom
//
// Carried over from /admin/sub-roles unchanged apart from the import and the
// permission mock: the screen itself is the reference flat section, so the
// regressions it pins — deactivated rows stay reachable, grouping is by
// registration role, deactivation keeps going through DELETE — are the same
// ones after the move. The permission gate is new coverage.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PlayerSubRole } from "@/types/admin.types";
import WorkspaceSubRolesSettingsPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getPlayerSubRoles = vi.fn();
const createPlayerSubRole = vi.fn();
const updatePlayerSubRole = vi.fn();
const deletePlayerSubRole = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    getPlayerSubRoles: (...args: unknown[]) => getPlayerSubRoles(...args),
    createPlayerSubRole: (...args: unknown[]) => createPlayerSubRole(...args),
    updatePlayerSubRole: (...args: unknown[]) => updatePlayerSubRole(...args),
    deletePlayerSubRole: (...args: unknown[]) => deletePlayerSubRole(...args)
  }
}));
let denied: string[] = [];
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    canAccessPermission: (permission: string) => !denied.includes(permission)
  })
}));
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (state: { currentWorkspaceId: number }) => unknown) =>
    selector({ currentWorkspaceId: 1 })
}));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

function subRole(overrides: Partial<PlayerSubRole> & { id: number }): PlayerSubRole {
  return {
    workspace_id: 1,
    role: "tank",
    slug: "main-tank",
    label: "Main Tank",
    description: null,
    sort_order: 0,
    is_active: true,
    ...overrides
  };
}

const CATALOG = [
  subRole({ id: 11, role: "tank", slug: "main-tank", label: "Main Tank" }),
  subRole({ id: 12, role: "tank", slug: "off-tank", label: "Off Tank", is_active: false }),
  subRole({ id: 21, role: "damage", slug: "hitscan", label: "Hitscan" })
];

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

async function mount() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <WorkspaceSubRolesSettingsPage />
      </QueryClientProvider>
    );
  });
  for (let turn = 0; turn < 5; turn += 1) {
    await act(async () => {
      await tick();
    });
  }
  return container;
}

function switchFor(scope: Element, accessibleName: string) {
  const node = [...scope.querySelectorAll("[role='switch']")].find(
    (candidate) => candidate.getAttribute("aria-label") === accessibleName
  );
  if (!node) throw new Error(`No switch labelled "${accessibleName}"`);
  return node;
}

function click(node: Element) {
  return act(async () => {
    node.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await tick();
  });
}

beforeEach(() => {
  document.body.innerHTML = "";
  denied = [];
  getPlayerSubRoles.mockReset().mockResolvedValue(CATALOG);
  createPlayerSubRole.mockReset().mockResolvedValue(CATALOG[0]);
  updatePlayerSubRole.mockReset().mockResolvedValue(CATALOG[0]);
  deletePlayerSubRole.mockReset().mockResolvedValue(undefined);
});

describe("WorkspaceSubRolesSettingsPage", () => {
  it("renders bare, letting the settings layout own the header", async () => {
    const scope = await mount();

    // The rail and the page header come from app/admin/settings/layout.tsx, so a
    // second "Sub-roles" heading here would be the section shouting its own name
    // twice.
    expect([...scope.querySelectorAll("h1")]).toHaveLength(0);
  });

  it("lists deactivated entries so they can be restored at all", async () => {
    const scope = await mount();

    // The form-builder tab only ever fetched active rows, which made a
    // deactivated sub-role unreachable from any UI.
    expect(getPlayerSubRoles).toHaveBeenCalledWith({ workspace_id: 1, include_inactive: true });
    expect(scope.textContent).toContain("Off Tank");
    expect(switchFor(scope, "Restore Off Tank").getAttribute("aria-checked")).toBe("false");
    expect(scope.textContent).toContain("1 of 2 active.");
  });

  it("groups each entry under its role's display label", async () => {
    const scope = await mount();
    const cards = [...scope.querySelectorAll("h2")].map((node) => node.textContent);

    expect(cards).toEqual(["Tank", "DPS", "Support"]);
    // "DPS" is the display label the `damage` role code renders under.
    const damageCard = [...scope.querySelectorAll("[data-ui='card']")].find(
      (card) => card.querySelector("h2")?.textContent === "DPS"
    );
    expect(damageCard?.textContent).toContain("Hitscan");
  });

  it("deactivates through DELETE so the player.delete gate is unchanged", async () => {
    const scope = await mount();

    await click(switchFor(scope, "Deactivate Main Tank"));

    expect(deletePlayerSubRole).toHaveBeenCalledWith(11);
    expect(updatePlayerSubRole).not.toHaveBeenCalled();
  });

  it("restores through a plain update", async () => {
    const scope = await mount();

    await click(switchFor(scope, "Restore Off Tank"));

    expect(updatePlayerSubRole).toHaveBeenCalledWith(12, { is_active: true });
    expect(deletePlayerSubRole).not.toHaveBeenCalled();
  });

  it("hides the add field without player.create and freezes the toggle without player.delete", async () => {
    denied = ["player.create", "player.delete"];
    const scope = await mount();

    const addButtons = [...scope.querySelectorAll("button")].filter((node) =>
      (node.textContent ?? "").trim().startsWith("Add")
    );
    expect(addButtons).toHaveLength(0);
    // Restoring is a plain update, so `player.delete` only stops deactivation.
    expect(switchFor(scope, "Deactivate Main Tank").hasAttribute("disabled")).toBe(true);
    expect(switchFor(scope, "Restore Off Tank").hasAttribute("disabled")).toBe(false);
  });
});
