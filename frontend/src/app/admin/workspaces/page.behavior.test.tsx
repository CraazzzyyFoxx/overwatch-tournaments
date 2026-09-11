// @vitest-environment happy-dom
//
// The workspaces list after P5-4. What is pinned here:
//  1. the gate `admin-navigation.ts` puts on `/admin/workspaces` — administering
//     at least one workspace, which is what `workspaceAdminVisible` means at a
//     null scope;
//  2. `?id=` opens the inspector, and the row click is what writes it;
//  3. editing leaves this screen: both the kebab and the inspector point at
//     `/admin/workspaces/[id]/general`, the section that owns the form. This
//     list must never grow one of its own;
//  4. one row action end to end: kebab -> typed confirmation -> DELETE;
//  5. six columns do not fit a phone, so rows render as cards below `md`.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, useEffect, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import type { Workspace } from "@/types/workspace.types";
import WorkspacesPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getAll = vi.fn();
const deleteWorkspace = vi.fn();

let superuser = true;
let managesAny = true;
let mayCreate = true;

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    isLoaded: true,
    isSuperuser: superuser,
    isWorkspaceAdmin: () => managesAny,
    canManageAnyWorkspace: () => managesAny,
    canUseCapability: () => mayCreate
  })
}));
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (
    selector: (state: { currentWorkspaceId: number; fetchWorkspaces: () => void }) => unknown
  ) => selector({ currentWorkspaceId: 1, fetchWorkspaces: () => undefined })
}));
vi.mock("@/services/workspace.service", () => ({
  default: {
    getAll: (...args: unknown[]) => getAll(...args),
    getOwner: vi.fn(async () => ({
      auth_user_id: 3,
      username: "ada",
      email: "ada@example.com",
      first_name: null,
      last_name: null,
      avatar_url: null
    })),
    create: vi.fn(),
    delete: (...args: unknown[]) => deleteWorkspace(...args),
    uploadIcon: vi.fn()
  }
}));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

const replace = vi.fn((url: string) => {
  window.history.replaceState(null, "", url);
  rerender?.();
});

let rerender: (() => void) | null = null;

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/workspaces",
  useRouter: () => ({ replace, push: replace }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));

function workspace(overrides: Partial<Workspace> = {}): Workspace {
  return {
    id: 8,
    slug: "rivals",
    name: "Rivals Cup",
    description: "A league of its own",
    icon_url: null,
    is_active: true,
    is_hidden: true,
    timezone: "Europe/Moscow",
    branding_enabled: false,
    brand_primary: null,
    brand_secondary: null,
    brand_background: null,
    brand_surface: null,
    brand_accent: null,
    brand_foreground: null,
    brand_muted: null,
    brand_border: null,
    brand_ring: null,
    brand_destructive: null,
    subdomain: "rivals",
    seo_title: null,
    seo_description: null,
    custom_domain: null,
    custom_domain_verified_at: null,
    custom_domain_verification_token: null,
    discord_guild_id: null,
    discord_guild_verified_at: null,
    verification_status: "unverified",
    default_division_grid_version_id: null,
    default_division_grid_version: null,
    newcomer_scope: "workspace",
    ...overrides
  };
}

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
  // Assigned in an effect, not during render: `next/navigation` is mocked, so
  // this is the only thing that re-reads the URL after a `replace`.
  useEffect(() => {
    rerender = () => force((value) => value + 1);
  }, []);
  return <>{render()}</>;
}

async function mount(search = "") {
  window.history.replaceState(null, "", `/admin/workspaces${search}`);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mounted.push({ root, container });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        {/* The admin layout mounts one; StatusIcon's tooltip needs it. */}
        <TooltipProvider>
          <Harness render={() => <WorkspacesPage />} />
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

async function type(input: HTMLInputElement, value: string) {
  // React tracks the DOM value on the node, so a plain assignment is swallowed
  // as "no change"; the native setter is what makes `onChange` fire.
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
    "value"
  )?.set;
  await act(async () => {
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await settle(2);
}

async function waitFor<T>(read: () => T | null | undefined | false, what: string): Promise<T> {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const value = read();
    if (value) return value as T;
    await settle(1, 25);
  }
  throw new Error(`timed out waiting for ${what}`);
}

function menuItem(text: string) {
  return Array.from(document.querySelectorAll('[role="menuitem"]')).find(
    (element) => element.textContent?.trim() === text
  );
}

function generalLinks(root: ParentNode): string[] {
  return Array.from(root.querySelectorAll("a"))
    .map((link) => link.getAttribute("href") ?? "")
    .filter((href) => href.startsWith("/admin/workspaces/"));
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
  superuser = true;
  managesAny = true;
  mayCreate = true;
  replace.mockClear();
  setViewportWidth(1280);
  getAll.mockReset().mockResolvedValue([workspace()]);
  deleteWorkspace.mockReset().mockResolvedValue(undefined);
  document.body.innerHTML = "";
});

afterEach(async () => {
  await act(async () => {
    for (const { root, container } of mounted.splice(0)) {
      root.unmount();
      container.remove();
    }
  });
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("/admin/workspaces", () => {
  it("refuses a caller who administers no workspace", async () => {
    superuser = false;
    managesAny = false;
    const container = await mount();

    expect(container.textContent).toContain("Unauthorized");
    expect(getAll).not.toHaveBeenCalled();
  });

  it("opens the inspector from ?id= and sends Edit to the General section", async () => {
    const container = await mount("?id=8");
    await waitFor(() => container.textContent?.includes("Rivals Cup"), "the workspace row");

    const inspector = await waitFor(
      () => document.querySelector('aside[aria-label="Row inspector"]'),
      "the inspector"
    );
    // The list shows none of this; the inspector is why the row is clickable.
    expect(inspector.textContent).toContain("Europe/Moscow");
    expect(inspector.textContent).toContain("Hidden from the public list");
    // The owner is not on the workspace payload at all — the inspector is the
    // only place on this screen that resolves it.
    await waitFor(() => inspector.textContent?.includes("@ada"), "the resolved owner");
    expect(generalLinks(inspector)).toContain("/admin/workspaces/8/general");
  });

  it("writes ?id= when a row is clicked", async () => {
    const container = await mount();
    const row = await waitFor(
      () => container.querySelector("tbody tr[tabindex]"),
      "the first data row"
    );

    await click(row);

    expect(new URLSearchParams(window.location.search).get("id")).toBe("8");
    expect(document.querySelector('aside[aria-label="Row inspector"]')).not.toBeNull();
  });

  it("edits through the kebab, which leaves for the settings sections", async () => {
    const container = await mount();
    await waitFor(() => container.textContent?.includes("Rivals Cup"), "the workspace row");

    await click(container.querySelector('button[aria-label="Actions for Rivals Cup"]'));
    const edit = await waitFor(() => menuItem("Edit workspace"), "the edit action");

    expect(edit.querySelector("a")?.getAttribute("href") ?? edit.getAttribute("href")).toBe(
      "/admin/workspaces/8/general"
    );
  });

  it("deletes a workspace only once its name is typed back", async () => {
    const container = await mount();
    await waitFor(() => container.textContent?.includes("Rivals Cup"), "the workspace row");

    await click(container.querySelector('button[aria-label="Actions for Rivals Cup"]'));
    await click(await waitFor(() => menuItem("Delete workspace"), "the delete action"));

    const dialog = await waitFor(
      () => document.querySelector('[role="alertdialog"]'),
      "the confirmation"
    );
    const confirm = Array.from(dialog.querySelectorAll("button")).find(
      (element) => element.textContent?.trim() === "Delete workspace"
    );
    // Everything in the workspace goes with it, so a click alone must not do it.
    expect(confirm?.hasAttribute("disabled")).toBe(true);

    await type(dialog.querySelector("input") as HTMLInputElement, "Rivals Cup");
    await click(confirm);

    expect(deleteWorkspace).toHaveBeenCalledWith(8);
  });

  it("renders rows as cards below md, where six columns do not fit", async () => {
    setViewportWidth(375);
    const container = await mount();
    const cards = await waitFor(() => {
      const list = container.querySelectorAll("ul[aria-label='Rows'] > li");
      return list.length > 0 ? list : null;
    }, "the mobile cards");

    expect(container.querySelector("table")).toBeNull();
    expect(cards[0].textContent).toContain("Rivals Cup");
    // The card is chosen, not the first three columns: the slug and the two
    // flags are what tells two workspaces apart on a phone.
    expect(cards[0].textContent).toContain("rivals");
    expect(cards[0].textContent).toContain("Hidden");
  });

  it("opens the create dialog for a non-superuser, because creation is no longer superuser-only", async () => {
    superuser = false;
    const container = await mount();
    const create = await waitFor(
      () =>
        Array.from(container.querySelectorAll("button")).find(
          (button) => button.textContent?.trim() === "Create workspace"
        ),
      "the create button"
    );

    expect(create.hasAttribute("disabled")).toBe(false);
    await click(create);

    const dialog = await waitFor(() => document.querySelector('[role="dialog"]'), "the dialog");
    expect(dialog.querySelector("#slug")).not.toBeNull();
    expect(dialog.querySelector("#name")).not.toBeNull();
  });

  // `workspace.self_create` is allow-by-default and revocable per account
  // (negative RBAC). The backend refuses a denied account outright, so the
  // button must not be offered as a guaranteed 403.
  it("drops the create button when the account's creation right was revoked", async () => {
    mayCreate = false;
    const container = await mount();
    await waitFor(() => container.textContent?.includes("Rivals Cup"), "the workspace row");

    expect(
      Array.from(container.querySelectorAll("button")).find(
        (button) => button.textContent?.trim() === "Create workspace"
      )
    ).toBeUndefined();
  });
});
