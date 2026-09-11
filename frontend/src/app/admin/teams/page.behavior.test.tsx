// @vitest-environment happy-dom
//
// The teams browser after P3-3. What is pinned here:
//  1. the `team.read` gate — the screen refuses instead of fetching rosters;
//  2. the tournament scope is a filter-bar chip on the same `?tournament=`
//     param the sibling browsers use, so a pinned link still opens pinned;
//  3. `?id=` opens the inspector with the roster summary, and a row click is
//     what writes it — the row no longer navigates away;
//  4. "Create team" still reads the same value the list is filtered by;
//  5. one row action end to end: kebab → confirm → delete request;
//  6. six columns do not fit a phone, so rows render as cards below `md`.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, useEffect, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Player, Team } from "@/types/team.types";
import TeamsPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getTeams = vi.fn();
const getTournaments = vi.fn();
const deleteTeam = vi.fn();

let permitted = true;

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    canAccessPermission: () => permitted,
    isLoaded: true,
    isSuperuser: false
  })
}));
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (state: { currentWorkspaceId: number }) => unknown) =>
    selector({ currentWorkspaceId: 1 })
}));
vi.mock("@/services/team.service", () => ({
  default: { getAll: (...args: unknown[]) => getTeams(...args) }
}));
vi.mock("@/services/tournament.service", () => ({
  default: { getAll: (...args: unknown[]) => getTournaments(...args) }
}));
vi.mock("@/services/admin.service", () => ({
  default: { deleteTeam: (...args: unknown[]) => deleteTeam(...args) }
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
  usePathname: () => "/admin/teams",
  useRouter: () => ({ replace, push: replace }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));

const TOURNAMENTS = [
  { id: 7, name: "MoonRise Mix Vol.4" },
  { id: 8, name: "MoonRise Draft Vol.2" }
];

function player(overrides: Partial<Player> = {}): Player {
  return {
    id: 501,
    created_at: new Date("2026-01-01T00:00:00Z"),
    updated_at: null,
    name: "Nova",
    sub_role: null,
    rank: 3400,
    division: 4,
    role: "dps",
    tournament_id: 7,
    user_id: 91,
    team_id: 42,
    is_newcomer: false,
    is_newcomer_role: false,
    is_substitution: false,
    related_player_id: null,
    user: { id: 91, name: "Nova" } as Player["user"],
    ...overrides
  };
}

function team(overrides: Partial<Team> = {}): Team {
  return {
    id: 42,
    created_at: new Date("2026-01-01T00:00:00Z"),
    updated_at: null,
    name: "Wombat Warriors",
    image_url: null,
    avg_sr: 3350.4,
    total_sr: 16752,
    captain_id: 91,
    tournament_id: 7,
    players: [player(), player({ id: 502, name: "Echo", user_id: 92, is_substitution: true, user: { id: 92, name: "Echo" } as Player["user"] })],
    tournament: { id: 7, name: "MoonRise Mix Vol.4" } as Team["tournament"],
    placement: 3,
    group: null,
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
  window.history.replaceState(null, "", `/admin/teams${search}`);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mounted.push({ root, container });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <Harness render={() => <TeamsPage />} />
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

function menuItem(text: string) {
  return Array.from(document.querySelectorAll('[role="menuitem"]')).find(
    (element) => element.textContent?.trim() === text
  );
}

function commandItem(label: string) {
  return Array.from(document.querySelectorAll('[cmdk-item=""]')).find(
    (item) => item.textContent?.trim().startsWith(label)
  );
}

function lastTournamentId(): unknown {
  return (getTeams.mock.calls.at(-1)?.[0] as { tournamentId?: unknown } | undefined)?.tournamentId;
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
  permitted = true;
  replace.mockClear();
  setViewportWidth(1280);
  getTeams.mockReset().mockResolvedValue({ results: [team()], total: 1, page: 1, per_page: 15 });
  getTournaments
    .mockReset()
    .mockResolvedValue({ results: TOURNAMENTS, total: 2, page: 1, per_page: -1 });
  deleteTeam.mockReset().mockResolvedValue(undefined);
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

describe("/admin/teams", () => {
  it("refuses the screen without team.read", async () => {
    permitted = false;
    const container = await mount();

    expect(container.textContent).toContain("Unauthorized");
    expect(getTeams).not.toHaveBeenCalled();
  });

  it("scopes the list from a chip and writes it to the URL", async () => {
    const container = await mount();
    await waitFor(() => container.textContent?.includes("Wombat Warriors"), "the team row");
    expect(lastTournamentId()).toBeNull();
    expect(getTeams).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, perPage: 15, tournamentId: null })
    );

    await click(container.querySelector('button[aria-label="Add filter"]'));
    await click(await waitFor(() => commandItem("Tournament"), "the Tournament filter"));
    await click(await waitFor(() => commandItem("MoonRise Draft Vol.2"), "the tournament option"));

    // The `tournament` spelling is the one the sibling browsers already use.
    expect(new URLSearchParams(window.location.search).get("tournament")).toBe("8");
    await waitFor(() => lastTournamentId() === 8, "the scoped roster request");
  });

  it("opens pinned from a link that carries the tournament", async () => {
    await mount("?tournament=7");

    await waitFor(() => lastTournamentId() === 7, "the scoped roster request");
    const chip = document.querySelector(
      'button[aria-label="Remove filter Tournament: MoonRise Mix Vol.4"]'
    );
    expect(chip).not.toBeNull();
  });

  it("opens the inspector for the clicked row and writes ?id=", async () => {
    const container = await mount();
    const row = await waitFor(
      () => container.querySelector("tbody tr[tabindex]"),
      "the first data row"
    );

    await click(row);

    // The row opens the inspector; it no longer navigates to the team page.
    expect(new URLSearchParams(window.location.search).get("id")).toBe("42");
    const inspector = await waitFor(
      () => document.querySelector('aside[aria-label="Row inspector"], [role="dialog"]'),
      "the inspector"
    );
    expect(inspector.textContent).toContain("Wombat Warriors");
    expect(inspector.textContent).toContain("Nova");
    expect(inspector.textContent).toContain("Echo");
    expect(
      Array.from(inspector.querySelectorAll("a")).some(
        (link) => link.getAttribute("href") === "/admin/teams/42"
      )
    ).toBe(true);
  });

  it("restores the inspector from ?id= on load", async () => {
    const container = await mount("?id=42");
    await waitFor(() => container.textContent?.includes("Wombat Warriors"), "the team row");

    const inspector = await waitFor(
      () => document.querySelector('aside[aria-label="Row inspector"], [role="dialog"]'),
      "the inspector"
    );
    expect(inspector.textContent).toContain("Captain");
  });

  it("keeps the create gate on the value the list is filtered by", async () => {
    const container = await mount();
    await waitFor(() => container.textContent?.includes("Wombat Warriors"), "the team row");
    expect(button("Create team")?.hasAttribute("disabled")).toBe(true);

    await click(container.querySelector('button[aria-label="Add filter"]'));
    await click(await waitFor(() => commandItem("Tournament"), "the Tournament filter"));
    await click(await waitFor(() => commandItem("MoonRise Mix Vol.4"), "the tournament option"));

    expect(button("Create team")?.hasAttribute("disabled")).toBe(false);
  });

  it("deletes a team from the row kebab through one confirmation", async () => {
    const container = await mount();
    await waitFor(() => container.textContent?.includes("Wombat Warriors"), "the team row");

    await click(container.querySelector('button[aria-label="Actions for Wombat Warriors"]'));
    await click(await waitFor(() => menuItem("Delete team"), "the delete action"));
    await click(await waitFor(() => button("Delete team"), "the confirm button"));

    expect(deleteTeam).toHaveBeenCalledWith(42);
  });

  it("renders rows as cards below md, where six columns do not fit", async () => {
    setViewportWidth(375);
    const container = await mount();
    const cards = await waitFor(() => {
      const list = container.querySelectorAll("ul[aria-label='Rows'] > li");
      return list.length > 0 ? list : null;
    }, "the mobile cards");

    expect(container.querySelector("table")).toBeNull();
    expect(cards[0].textContent).toContain("Wombat Warriors");
    // The card is chosen, not the first three columns: the tournament and the
    // roster size are what a phone needs from a team.
    expect(cards[0].textContent).toContain("MoonRise Mix Vol.4");
    expect(cards[0].textContent).toContain("2 players");
  });
});
