// @vitest-environment happy-dom
//
// The person hub (People › one identity). What is pinned here:
//  1. the `user.read` gate — the hub refuses instead of rendering empty tabs;
//  2. `?tab=` is the whole tab state: a deep link opens that tab directly and
//     an unknown value falls back to Identity;
//  3. the detail query lands under the EXACT key `breadcrumb-registry.ts`
//     declares for the `people` segment, which is the only reason the crumb
//     reads a person's name instead of "Details";
//  4. Participations is the old /admin/players table, scoped to one person —
//     the column order, the pinned Name column and the one Div · Rank cell are
//     carried over from `players/page.behavior.test.tsx`, together with the
//     rule that a participation joins a team inside one tournament;
//  5. one action end to end: edit a participation through the shared form.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, useEffect, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import PersonHubPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getUsers = vi.fn();
const getUserTournaments = vi.fn();
const getUserAchievements = vi.fn();
const getPlayerSubRoles = vi.fn();
const updatePlayer = vi.fn();
const createPlayer = vi.fn();
const deletePlayer = vi.fn();
const listUsersAll = vi.fn();
const getTournaments = vi.fn();
const getTeams = vi.fn();

let permitted = true;

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  NextIntlClientProvider: ({ children }: { children: ReactNode }) => children
}));
vi.mock("@/lib/datetime/client", () => ({
  useFormatter: () => ({ dateTime: (value: Date) => value.toISOString() })
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
  useWorkspaceStore: (
    selector: (state: {
      currentWorkspaceId: number;
      getCurrentWorkspace: () => null;
    }) => unknown
  ) => selector({ currentWorkspaceId: 1, getCurrentWorkspace: () => null })
}));

// Rank history is a chart with its own suite; the hub only has to mount it.
vi.mock("@/components/RankHistory", () => ({ default: () => <div>Rank history</div> }));

vi.mock("@/services/admin.service", () => ({
  default: {
    getUsers: (...args: unknown[]) => getUsers(...args),
    getPlayerSubRoles: (...args: unknown[]) => getPlayerSubRoles(...args),
    updatePlayer: (...args: unknown[]) => updatePlayer(...args),
    createPlayer: (...args: unknown[]) => createPlayer(...args),
    deletePlayer: (...args: unknown[]) => deletePlayer(...args),
    getRankCollectionStatus: vi.fn().mockResolvedValue([]),
    triggerRankCollection: vi.fn(),
    getSubscriptionCollectionStatus: vi.fn().mockResolvedValue([]),
    getSubscriptionCheckLog: vi.fn().mockResolvedValue([]),
    triggerSubscriptionCollection: vi.fn(),
    uploadUserAvatar: vi.fn(),
    deleteUserAvatar: vi.fn(),
    updateUser: vi.fn()
  }
}));
vi.mock("@/services/user.service", () => ({
  default: {
    getUserTournaments: (...args: unknown[]) => getUserTournaments(...args),
    getUserAchievements: (...args: unknown[]) => getUserAchievements(...args),
    searchUsers: vi.fn().mockResolvedValue([])
  }
}));
vi.mock("@/services/rank.service", () => ({
  default: { getUserCurrentRanks: vi.fn().mockResolvedValue({ ranks: [] }) }
}));
vi.mock("@/services/rbac.service", () => ({
  rbacService: {
    listUsersAll: (...args: unknown[]) => listUsersAll(...args),
    getUser: vi.fn(),
    assignLinkedPlayer: vi.fn()
  }
}));
vi.mock("@/services/tournament.service", () => ({
  default: { getAll: (...args: unknown[]) => getTournaments(...args) }
}));
vi.mock("@/services/team.service", () => ({
  default: { getAll: (...args: unknown[]) => getTeams(...args) }
}));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));
vi.mock("@/app/actions/users", () => ({ revalidateUser: vi.fn() }));

const replace = vi.fn((url: string) => {
  window.history.replaceState(null, "", url);
  rerender?.();
});

let rerender: (() => void) | null = null;

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "42" }),
  usePathname: () => "/admin/people/42",
  useRouter: () => ({ replace, push: replace }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));

const PERSON = {
  id: 42,
  created_at: new Date("2026-01-01T00:00:00Z"),
  updated_at: null,
  name: "nnniik#2515",
  avatar_url: null,
  social_accounts: []
};

const PARTICIPATIONS = [
  {
    id: 7,
    name: "MoonRise Mix Vol.4",
    is_league: false,
    team_id: 3,
    team: "nnniik",
    players: [
      {
        id: 11,
        name: "nnniik#2515",
        role: "support",
        sub_role: null,
        rank: 1800,
        division: 9,
        user_id: 42,
        is_substitution: false,
        is_newcomer: true,
        is_newcomer_role: false,
        related_player_id: null
      }
    ],
    closeness: 0,
    placement: 3,
    count_teams: 8,
    won: 4,
    lost: 2,
    draw: 0,
    maps_won: 9,
    maps_lost: 5,
    division: 9,
    division_grid_version: null,
    role: "support"
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
          <Harness render={() => <PersonHubPage />} />
        </TooltipProvider>
      </QueryClientProvider>
    );
  });
  await settle();
  return { container, client };
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

function menuItem(text: string) {
  return Array.from(document.querySelectorAll('[role="menuitem"]')).find(
    (element) => element.textContent?.trim() === text
  );
}

/** `useIsMobile` reads `innerWidth`; `matchMedia` only carries its listener. */
function mockViewport(width: number) {
  Object.defineProperty(window, "innerWidth", { value: width, configurable: true });
  window.matchMedia = ((query: string) => ({
    matches: width < 768,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false
  })) as unknown as typeof window.matchMedia;
}

function activeTab() {
  return document.querySelector('[aria-current="page"]')?.textContent?.trim();
}

function headerCells(container: HTMLElement) {
  // The table's width filler is `aria-hidden`; only data columns are asserted on.
  return Array.from(container.querySelectorAll("thead th:not([aria-hidden])"));
}

beforeEach(() => {
  permitted = true;
  replace.mockClear();
  getUsers.mockReset().mockResolvedValue({ results: [PERSON], total: 1, page: 1, per_page: -1 });
  getUserTournaments.mockReset().mockResolvedValue(PARTICIPATIONS);
  getUserAchievements.mockReset().mockResolvedValue([]);
  getPlayerSubRoles.mockReset().mockResolvedValue([]);
  updatePlayer.mockReset().mockResolvedValue({});
  createPlayer.mockReset().mockResolvedValue({});
  deletePlayer.mockReset().mockResolvedValue(undefined);
  listUsersAll.mockReset().mockResolvedValue([]);
  getTournaments
    .mockReset()
    .mockResolvedValue({ results: [{ id: 7, name: "MoonRise Mix Vol.4" }], total: 1, page: 1, per_page: -1 });
  getTeams.mockReset().mockResolvedValue({ results: [], total: 0, page: 1, per_page: -1 });
  mockViewport(1280);
  window.history.replaceState(null, "", "/admin/people/42");
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

describe("person hub", () => {
  it("refuses without user.read", async () => {
    permitted = false;
    const { container } = await mount();

    expect(container.textContent).toContain("Unauthorized");
    expect(getUsers).not.toHaveBeenCalled();
  });

  it("caches the person under the key the breadcrumb reads", async () => {
    const { client } = await mount();
    await waitFor(() => client.getQueryData(["admin", "person", 42]), "the person in the cache");

    expect(client.getQueryData<{ name: string }>(["admin", "person", 42])?.name).toBe(
      "nnniik#2515"
    );
  });

  it("defaults to Identity and never fetches another tab's data", async () => {
    const { container } = await mount();
    await waitFor(() => container.textContent?.includes("Social identities"), "the identity tab");

    expect(activeTab()).toBe("Identity");
    expect(getUserTournaments).not.toHaveBeenCalled();
  });

  it("opens ?tab=participations directly", async () => {
    window.history.replaceState(null, "", "/admin/people/42?tab=participations");
    const { container } = await mount();
    await waitFor(() => container.textContent?.includes("MoonRise Mix Vol.4"), "the participation");

    expect(activeTab()).toBe("Participations");
    expect(getUserTournaments).toHaveBeenCalledWith(42, 1);
  });

  it("falls back to Identity for a tab that does not exist", async () => {
    window.history.replaceState(null, "", "/admin/people/42?tab=nonsense");
    await mount();

    expect(activeTab()).toBe("Identity");
  });

  it("orders the participation columns name-first and pins the name", async () => {
    window.history.replaceState(null, "", "/admin/people/42?tab=participations");
    const { container } = await mount();
    await waitFor(() => container.textContent?.includes("MoonRise Mix Vol.4"), "the participation");

    expect(headerCells(container).map((cell) => cell.textContent?.trim())).toEqual([
      "Name",
      "Team",
      "Tournament",
      "Role",
      "Div · Rank",
      "Sub-role",
      "Flags",
      // The kebab column: the pencil+trash pair is gone, the header is sr-only.
      "Actions"
    ]);
    expect(headerCells(container)[0].className).toContain("admin-sticky-col");
    expect(container.querySelector("tbody tr")?.firstElementChild?.className).toContain(
      "admin-sticky-col"
    );
  });

  it("drops seven columns into a card on a narrow viewport", async () => {
    mockViewport(375);
    window.history.replaceState(null, "", "/admin/people/42?tab=participations");
    const { container } = await mount();
    await waitFor(() => container.textContent?.includes("MoonRise Mix Vol.4"), "the participation");

    // Seven columns do not fit 375px, so the table is not rendered at all and
    // the card names the facts that identify the row.
    expect(container.querySelector("thead")).toBeNull();
    expect(container.textContent).toContain("nnniik#2515");
    expect(container.textContent).toContain("nnniik · MoonRise Mix Vol.4");
  });

  it("shows the division icon and the rank in one cell", async () => {
    window.history.replaceState(null, "", "/admin/people/42?tab=participations");
    const { container } = await mount();
    await waitFor(() => container.textContent?.includes("MoonRise Mix Vol.4"), "the participation");

    const divisionCell = container.querySelectorAll("tbody tr td")[4];
    expect(divisionCell.querySelector("img")).not.toBeNull();
    expect(divisionCell.textContent).toContain("1800");
  });

  it("edits a participation through the shared form", async () => {
    window.history.replaceState(null, "", "/admin/people/42?tab=participations");
    const { container } = await mount();
    await waitFor(() => container.textContent?.includes("MoonRise Mix Vol.4"), "the participation");

    await click(
      container.querySelector(
        'button[aria-label="Actions for nnniik#2515 in MoonRise Mix Vol.4"]'
      )
    );
    await click(await waitFor(() => menuItem("Edit participation"), "the edit action"));

    const nameField = await waitFor(
      () => document.querySelector<HTMLInputElement>("#player-edit-name"),
      "the name field"
    );
    expect(nameField.value).toBe("nnniik#2515");
    await type(nameField, "nnniik#9999");
    await click(button("Save"));

    expect(updatePlayer).toHaveBeenCalledWith(
      11,
      expect.objectContaining({ name: "nnniik#9999", role: "Support", rank: 1800 })
    );
  });

  it("keeps a new participation blocked until it names a tournament and a team", async () => {
    window.history.replaceState(null, "", "/admin/people/42?tab=participations");
    const { container } = await mount();
    await waitFor(() => container.textContent?.includes("MoonRise Mix Vol.4"), "the participation");

    await click(button("Add participation"));
    // A player joins a team inside ONE tournament, so the team picker stays
    // inert until the tournament is chosen — the gate the old cross-tournament
    // players screen put on its Create button.
    const teamPicker = await waitFor(
      () => document.querySelector<HTMLButtonElement>("#player-create-team"),
      "the team picker"
    );
    expect(teamPicker.disabled).toBe(true);

    await click(button("Save"));
    expect(createPlayer).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain("Pick the tournament this participation belongs to.");
  });
});
