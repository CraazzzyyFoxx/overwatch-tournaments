// @vitest-environment happy-dom
//
// Three things this section has to get right, all of them regressions of the
// four-hand-rolled-tables screen it replaces: the scope lives in the URL rather
// than in the page structure, resetting a built-in reads differently from
// deleting a custom status, and a reader without `team.update` is offered no
// mutation at all.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { BalancerCustomStatus } from "@/types/balancer-admin.types";
import WorkspaceStatusesSettingsPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const listStatusCatalog = vi.fn();
const deleteCustomStatus = vi.fn();
const resetBuiltinStatusOverride = vi.fn();

vi.mock("@/services/balancer-admin.service", () => ({
  default: {
    listStatusCatalog: (...args: unknown[]) => listStatusCatalog(...args),
    createCustomStatus: vi.fn(),
    updateCustomStatus: vi.fn(),
    upsertBuiltinStatusOverride: vi.fn(),
    deleteCustomStatus: (...args: unknown[]) => deleteCustomStatus(...args),
    resetBuiltinStatusOverride: (...args: unknown[]) => resetBuiltinStatusOverride(...args)
  }
}));

let canManage = true;
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ canAccessPermission: () => canManage })
}));
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (state: { currentWorkspaceId: number }) => unknown) =>
    selector({ currentWorkspaceId: 1 })
}));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

// `useQueryParams` reads the params next/navigation reports and writes through
// the router, so the URL is the one under test here.
let params = new URLSearchParams();
const replace = vi.fn((url: string) => {
  params = new URLSearchParams(url.includes("?") ? url.slice(url.indexOf("?") + 1) : "");
});
vi.mock("next/navigation", () => ({
  useSearchParams: () => params,
  usePathname: () => "/admin/settings/statuses",
  useRouter: () => ({ replace, push: vi.fn() })
}));
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  )
}));

function status(overrides: Partial<BalancerCustomStatus> & { slug: string }): BalancerCustomStatus {
  return {
    id: 0,
    workspace_id: 1,
    scope: "registration",
    kind: "builtin",
    is_override: false,
    can_delete: false,
    can_reset: false,
    icon_slug: null,
    icon_color: null,
    name: overrides.slug,
    description: null,
    excludes_from_balancer: false,
    excludes_from_ready: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: null,
    ...overrides
  };
}

const CATALOG: BalancerCustomStatus[] = [
  status({ slug: "pending", name: "Pending", can_reset: true, is_override: true }),
  status({ slug: "ready", name: "Ready", scope: "balancer", can_reset: true }),
  status({
    id: 51,
    slug: "awaiting-captain",
    name: "Awaiting captain",
    kind: "custom",
    can_delete: true
  }),
  status({
    id: 52,
    slug: "benched",
    name: "Benched",
    scope: "balancer",
    kind: "custom",
    can_delete: true,
    excludes_from_balancer: true
  })
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
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider client={client}>
          <WorkspaceStatusesSettingsPage />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  for (let turn = 0; turn < 5; turn += 1) {
    await act(async () => {
      await tick();
    });
  }
  return container;
}

/** Radix opens on `pointerdown`, so a bare click never reaches the menu. */
function open(node: Element) {
  return act(async () => {
    node.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await tick();
  });
}

function click(node: Element) {
  return act(async () => {
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await tick();
  });
}

function kebabFor(name: string): Element {
  const node = [...document.querySelectorAll("[aria-label^='Actions for']")].find((candidate) =>
    (candidate.getAttribute("aria-label") ?? "").includes(name)
  );
  if (!node) throw new Error(`no kebab for "${name}"`);
  return node;
}

function menuItem(label: string): Element {
  const node = [...document.querySelectorAll("[role='menuitem']")].find(
    (candidate) => (candidate.textContent ?? "").trim() === label
  );
  if (!node) throw new Error(`no menu item "${label}"`);
  return node;
}

function confirmButton(): Element {
  // The AlertDialog action is the only button whose label is the intent's.
  const node = [...document.querySelectorAll("button")].find((candidate) =>
    /^(Reset status|Delete status)$/.test((candidate.textContent ?? "").trim())
  );
  if (!node) throw new Error("no confirm button");
  return node;
}

beforeEach(() => {
  document.body.innerHTML = "";
  params = new URLSearchParams();
  canManage = true;
  replace.mockClear();
  listStatusCatalog.mockReset().mockResolvedValue(CATALOG);
  deleteCustomStatus.mockReset().mockResolvedValue(undefined);
  resetBuiltinStatusOverride.mockReset().mockResolvedValue(undefined);
});

describe("WorkspaceStatusesSettingsPage", () => {
  it("shows one table with a System and a Custom group", async () => {
    const container = await mount();

    // Group headers, not four tables: the same row shape either side of them.
    const groups = [...container.querySelectorAll("tbody tr:not([data-row-id]) button")].map((header) =>
      (header.textContent ?? "").replace(/\d+$/, "")
    );
    expect(groups).toEqual(["System", "Custom"]);
    expect(container.querySelectorAll("table")).toHaveLength(1);
    expect(container.textContent).toContain("Awaiting captain");
    // The pool exclusion is a boolean exception: an icon in the Effects column.
    expect(container.querySelector('[aria-label="Excludes pool"]')).not.toBeNull();
  });

  it("keeps the scope filter in the URL instead of in the page structure", async () => {
    params = new URLSearchParams("scope=balancer");
    const container = await mount();

    // Only the balancer-scope statuses survive the chip that the URL declares.
    expect(container.textContent).toContain("Benched");
    expect(container.textContent).not.toContain("Awaiting captain");

    const chip = [...container.querySelectorAll("button")].find((node) =>
      (node.textContent ?? "").includes("Scope")
    );
    expect(chip).toBeDefined();
  });

  it("resets a built-in through a different intent than it deletes a custom status", async () => {
    await mount();

    await open(kebabFor("the Pending status"));
    // A built-in cannot be deleted, only reset — the two actions are not the
    // same row action wearing different words.
    expect(() => menuItem("Delete")).toThrow();
    await click(menuItem("Reset to default"));

    expect(document.body.textContent).toContain("Reset system status");
    expect(document.body.textContent).toContain("goes back to its default built-in name");
    await click(confirmButton());
    expect(resetBuiltinStatusOverride).toHaveBeenCalledWith(1, "registration", "pending");
    expect(deleteCustomStatus).not.toHaveBeenCalled();
  });

  it("deletes a custom status with the destructive intent", async () => {
    await mount();

    await open(kebabFor("the Awaiting captain status"));
    expect(() => menuItem("Reset to default")).toThrow();
    await click(menuItem("Delete"));

    expect(document.body.textContent).toContain("Delete custom status");
    expect(document.body.textContent).toContain("is removed from the catalog");
    await click(confirmButton());
    expect(deleteCustomStatus).toHaveBeenCalledWith(1, 51);
    expect(resetBuiltinStatusOverride).not.toHaveBeenCalled();
  });

  it("offers no mutation without team.update", async () => {
    canManage = false;
    const container = await mount();

    expect(container.textContent).toContain("Pending");
    expect(container.textContent).not.toContain("Add status");
    // An action a caller may not take is absent, not disabled.
    expect(container.querySelectorAll("[aria-label^='Actions for']")).toHaveLength(0);
  });
});
