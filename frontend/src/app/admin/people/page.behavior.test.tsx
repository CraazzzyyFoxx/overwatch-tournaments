// @vitest-environment happy-dom
//
// People — the identity browser that replaced /admin/users and /admin/players.
// What is pinned here:
//  1. the `user.read` gate — the page refuses instead of rendering an empty
//     table, and it never asks the API for identities it may not see;
//  2. chips live in the URL and are forwarded as query params on the paged
//     list (`has_account` / `unlinked` / `tournament_id`) — the table is
//     server-mode, so narrowing is the server's job;
//  3. `?id=` opens the inspector, is written by a row click, and survives a
//     reload as a deep link;
//  4. one action end to end: create identity → POST.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, useEffect, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import PeoplePage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getUsers = vi.fn();
const createUser = vi.fn();
const deleteUser = vi.fn();
const listUsersAll = vi.fn();
const getTournaments = vi.fn();

let permitted = true;

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  NextIntlClientProvider: ({ children }: { children: ReactNode }) => children
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    canAccessPermission: () => permitted,
    hasPermission: () => permitted,
    isSuperuser: false,
    isLoaded: true
  })
}));

vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (state: { currentWorkspaceId: number }) => unknown) =>
    selector({ currentWorkspaceId: 1 })
}));

vi.mock("@/services/admin.service", () => ({
  default: {
    getUsers: (...args: unknown[]) => getUsers(...args),
    createUser: (...args: unknown[]) => createUser(...args),
    deleteUser: (...args: unknown[]) => deleteUser(...args),
    uploadUserAvatar: vi.fn(),
    deleteUserAvatar: vi.fn(),
    updateUser: vi.fn()
  }
}));
vi.mock("@/services/rbac.service", () => ({
  rbacService: {
    listUsersAll: (...args: unknown[]) => listUsersAll(...args),
    assignLinkedPlayer: vi.fn()
  }
}));
vi.mock("@/services/tournament.service", () => ({
  default: { getAll: (...args: unknown[]) => getTournaments(...args) }
}));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));
// Server action — nothing to revalidate in a DOM test.
vi.mock("@/app/actions/users", () => ({ revalidateUser: vi.fn() }));

const replace = vi.fn((url: string) => {
  window.history.replaceState(null, "", url);
  rerender?.();
});

let rerender: (() => void) | null = null;

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/people",
  useRouter: () => ({ replace, push: replace }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));

const PEOPLE = [
  {
    id: 11,
    created_at: new Date("2026-01-01T00:00:00Z"),
    updated_at: null,
    name: "nnniik#2515",
    avatar_url: null,
    social_accounts: [
      {
        id: 1,
        user_id: 11,
        provider: "discord" as const,
        username: "nnniik",
        url: null,
        is_verified: true,
        is_primary: true
      }
    ]
  },
  {
    id: 12,
    created_at: new Date("2026-01-02T00:00:00Z"),
    updated_at: null,
    name: "Karnage#22778",
    avatar_url: null,
    social_accounts: []
  }
];

const AUTH_ACCOUNTS = [
  {
    id: 90,
    email: "nnniik@example.com",
    username: "nnniik",
    is_active: true,
    is_superuser: false,
    is_verified: true,
    linked_players: [
      { player_id: 11, player_name: "nnniik#2515", is_primary: true, linked_at: "2026-01-01" }
    ],
    roles: [],
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

async function mount() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mounted.push({ root, container });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <TooltipProvider>
          <Harness render={() => <PeoplePage />} />
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
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
    "value"
  )!.set!;
  await act(async () => {
    setter.call(input, value);
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

function button(text: string) {
  return Array.from(document.querySelectorAll("button")).find(
    (element) => element.textContent?.trim() === text
  );
}

function commandItem(label: string) {
  return Array.from(document.querySelectorAll('[cmdk-item=""]')).find(
    (item) => item.textContent?.trim().startsWith(label)
  );
}

function bodyRows(container: HTMLElement) {
  return Array.from(container.querySelectorAll("tbody tr"));
}

beforeEach(() => {
  permitted = true;
  replace.mockClear();
  getUsers.mockReset().mockImplementation((params: Record<string, unknown> = {}) => {
    let results = PEOPLE;
    if (params.has_account) results = PEOPLE.filter((person) => person.id === 11);
    if (params.unlinked) results = PEOPLE.filter((person) => person.social_accounts.length === 0);
    return Promise.resolve({
      results,
      total: results.length,
      page: (params.page as number) ?? 1,
      per_page: (params.per_page as number) ?? 20
    });
  });
  createUser.mockReset().mockResolvedValue({ id: 13, name: "New#1", social_accounts: [] });
  deleteUser.mockReset().mockResolvedValue(undefined);
  listUsersAll.mockReset().mockResolvedValue(AUTH_ACCOUNTS);
  getTournaments
    .mockReset()
    .mockResolvedValue({ results: [{ id: 7, name: "MoonRise Mix Vol.4" }], total: 1, page: 1, per_page: -1 });
  window.history.replaceState(null, "", "/admin/people");
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

describe("People", () => {
  it("refuses without user.read and never asks for identities", async () => {
    permitted = false;
    const container = await mount();

    expect(container.textContent).toContain("Unauthorized");
    expect(getUsers).not.toHaveBeenCalled();
  });

  it("lists every identity with its handles and its linked account", async () => {
    const container = await mount();
    await waitFor(() => container.textContent?.includes("nnniik#2515"), "the first identity");

    expect(bodyRows(container)).toHaveLength(2);
    expect(container.textContent).toContain("No identities linked");
    expect(container.textContent).toContain("Not linked");
    expect(getUsers).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, per_page: 20 })
    );
    expect(getUsers.mock.calls.some((call) => call[0]?.per_page === -1)).toBe(false);
  });

  it("writes the has-account chip to the URL and narrows the list by it", async () => {
    const container = await mount();
    await waitFor(() => container.textContent?.includes("Karnage#22778"), "both identities");

    await click(container.querySelector('button[aria-label="Add filter"]'));
    await click(await waitFor(() => commandItem("Has account"), "the Has account filter"));

    expect(new URLSearchParams(window.location.search).get("has-account")).toBe("1");
    await waitFor(() => bodyRows(container).length === 1, "the narrowed list");
    expect(container.textContent).toContain("nnniik#2515");
    expect(container.textContent).not.toContain("Karnage#22778");
    expect(getUsers).toHaveBeenCalledWith(expect.objectContaining({ has_account: true }));
  });

  it("restores a chip from the URL on load", async () => {
    window.history.replaceState(null, "", "/admin/people?unlinked=1");
    const container = await mount();

    // `unlinked` is about handles, not accounts: only the identity with no
    // social account survives it.
    await waitFor(() => bodyRows(container).length === 1, "the narrowed list");
    expect(container.textContent).toContain("Karnage#22778");
    expect(getUsers).toHaveBeenCalledWith(expect.objectContaining({ unlinked: true }));
  });

  it("opens the inspector for the clicked row and writes ?id=", async () => {
    const container = await mount();
    const row = await waitFor(
      () => container.querySelector("tbody tr[tabindex]"),
      "the first data row"
    );

    await click(row);

    expect(new URLSearchParams(window.location.search).get("id")).toBe("11");
    const inspector = await waitFor(
      () => document.querySelector('aside[aria-label="Row inspector"], [role="dialog"]'),
      "the inspector"
    );
    expect(inspector.textContent).toContain("Identity #11");
    expect(
      document.querySelector('a[href="/admin/people/11"]')?.textContent
    ).toContain("Open page");
  });

  it("opens the inspector straight from a deep link", async () => {
    window.history.replaceState(null, "", "/admin/people?id=12");
    await mount();

    const inspector = await waitFor(
      () => document.querySelector('aside[aria-label="Row inspector"], [role="dialog"]'),
      "the inspector"
    );
    expect(inspector.textContent).toContain("Karnage#22778");
  });

  it("creates an identity from the toolbar", async () => {
    const container = await mount();
    await waitFor(() => container.textContent?.includes("nnniik#2515"), "the list");

    await click(button("Create identity"));
    const nameField = await waitFor(
      () => document.querySelector<HTMLInputElement>('input[placeholder^="Player name"]'),
      "the name field"
    );
    await type(nameField, "Fresh#1111");
    await click(button("Save"));

    expect(createUser).toHaveBeenCalledWith({ name: "Fresh#1111" });
  });
});
