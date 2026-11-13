// @vitest-environment happy-dom
//
// The workspace-wide Matches browser (P3-1). What is pinned here:
//  1. the `match.read` gate — five sidebar entries became one screen, so the
//     grant is checked once, on the screen;
//  2. `?view=` is the only state the switch owns, and it survives a reload;
//  3. switching view keeps the shared tournament scope and the Game chip and
//     drops the row id, because an encounter id means nothing in the
//     parsed-maps view;
//  4. the tournament chip is removable here — inside a hub the tournament is
//     not a filter at all — and applies under every game;
//  5. below `md` the rows become cards: these tables carry more than four
//     columns, so a phone gets the card layout instead of a sideways scroll;
//  6. a Game chip pick drops the map always and the tournament scope only when
//     it is another game's, keeping the view.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, useEffect, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@craazzzyyfoxx/admin-kit/ui/tooltip";
import { en as kitMessages } from "@craazzzyyfoxx/admin-kit/messages";
import en from "@/i18n/messages/en.json";
import type { Encounter } from "@/types/encounter.types";
import AdminMatchesPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getEncounters = vi.fn();
const getTournaments = vi.fn();
const getStandings = vi.fn();
const getTournament = vi.fn();
const getStages = vi.fn();

let permitted = true;

const MESSAGES = {
  common: en.common,
  kit: en.kit,
  kitAudit: en.kitAudit,
  kitTable: en.kitTable,
  ...kitMessages,
  bracket: en.bracket,
  accountSettings: { logDirectory: en.accountSettings.logDirectory },
  adminTournaments: { standings: en.adminTournaments.standings },
  adminMatches: {
    matches: en.adminMatches.matches,
    audit: en.adminMatches.audit,
    encounters: en.adminMatches.encounters,
    reports: en.adminMatches.reports,
    parsed: en.adminMatches.parsed,
    common: en.adminMatches.common
  }
};

vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  return {
    ...actual,
    useTranslations: (namespace?: string) => {
      try {
        return actual.createTranslator({ locale: "en", messages: MESSAGES, namespace: namespace as never });
      } catch {
        return ((key: string) => key) as ReturnType<typeof actual.useTranslations>;
      }
    },
    NextIntlClientProvider: ({ children }: { children: ReactNode }) => children
  };
});
vi.mock("@/lib/datetime/client", () => ({
  useFormatter: () => ({
    dateTime: (value: Date) => value.toISOString(),
    number: (value: number) => String(value),
    relativeTime: () => ""
  })
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    canAccessPermission: () => permitted,
    isLoaded: true,
    isSuperuser: false
  })
}));

vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (state: { currentWorkspaceId: number }) => unknown) =>
    selector({ currentWorkspaceId: 4 })
}));

vi.mock("@/services/encounter.service", () => ({
  default: { getAll: (...args: unknown[]) => getEncounters(...args) }
}));
vi.mock("@/services/team.service", () => ({
  default: { getAll: vi.fn().mockResolvedValue({ results: [], total: 0, page: 1, per_page: -1 }) }
}));
vi.mock("@/services/tournament.service", () => ({
  default: {
    getAll: (...args: unknown[]) => getTournaments(...args),
    getStandings: (...args: unknown[]) => getStandings(...args)
  }
}));
vi.mock("@/services/admin.service", () => ({
  default: {
    getTournament: (...args: unknown[]) => getTournament(...args),
    getStages: (...args: unknown[]) => getStages(...args),
    createEncounter: vi.fn(),
    updateEncounter: vi.fn(),
    deleteEncounter: vi.fn(),
    syncEncountersFromChallonge: vi.fn(),
    updateStanding: vi.fn(),
    deleteStanding: vi.fn(),
    recalculateStandings: vi.fn(),
    listEncounterReports: vi.fn().mockResolvedValue({
      results: [],
      total: 0,
      page: 1,
      per_page: 25
    }),
    listAdminMatches: vi.fn().mockResolvedValue({ results: [], total: 0, page: 1, per_page: 25 })
  }
}));
vi.mock("@/services/catalog.service", () => ({
  default: { list: vi.fn().mockResolvedValue({ results: [], total: 0, page: 1, per_page: -1 }) }
}));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));
vi.mock("@/components/kit/AuditTrailSheet", () => ({
  AuditTrailButton: () => <button type="button">Change history</button>
}));
const scopeGame = vi.hoisted(() => ({ value: null as string | null }));
vi.mock("@/hooks/useGameScope", async () => {
  const { gameScopeState } = await import("@/test/game-scope");
  return { useGameScope: () => gameScopeState(scopeGame.value) };
});
vi.mock("@/hooks/useGameDescriptors", async () => {
  const { GAME_DESCRIPTORS } = await import("@/test/game-scope");
  return { useGameDescriptors: () => GAME_DESCRIPTORS };
});

const replace = vi.fn((url: string) => {
  window.history.replaceState(null, "", url);
  rerender?.();
});

let rerender: (() => void) | null = null;

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/matches",
  useRouter: () => ({ replace, push: replace }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));

function encounter(overrides: Partial<Encounter> = {}): Encounter {
  return {
    id: 8812,
    created_at: new Date("2026-05-01T00:00:00Z"),
    updated_at: null,
    name: "Team C vs Team D",
    round: 3,
    best_of: 3,
    tournament_id: 78,
    stage_id: 5,
    stage_item_id: null,
    challonge_id: null,
    status: "PENDING",
    closeness: null,
    has_logs: false,
    result_status: "none",
    scheduled_at: null,
    started_at: null,
    ended_at: null,
    played_at: null,
    is_live: false,
    is_final: false,
    current_map_index: null,
    confirmed_at: null,
    matches: [],
    slot_count: 2,
    result_source: null,
    result_version: 1,
    games: [],
    teams: [
      { id: 31, slot: 1, team_id: 3, name: "Team C", seed: null, score: 1, placement: null, active: true },
      { id: 41, slot: 2, team_id: 4, name: "Team D", seed: null, score: 2, placement: null, active: true }
    ],
    tournament: { id: 78, name: "OWT 78" } as Encounter["tournament"],
    stage: { id: 5, name: "Groups" } as Encounter["stage"],
    stage_item: null,
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

/** Polls with a real delay: every view is code-split. */
async function waitFor<T>(read: () => T | null | undefined | false, what: string): Promise<T> {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const value = read();
    if (value) return value as T;
    await settle(1, 25);
  }
  throw new Error(`timed out waiting for ${what}`);
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
          <Harness render={() => <AdminMatchesPage />} />
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

function tab(scope: ParentNode, label: string) {
  return Array.from(scope.querySelectorAll("nav a")).find(
    (link) => link.textContent?.trim() === label
  );
}

/** The chip popover portals out of the page; an option's label sits beside its game mark. */
function commandItem(label: string) {
  return Array.from(document.querySelectorAll('[cmdk-item=""]')).find((item) =>
    (item.querySelector(".truncate") ?? item).textContent?.trim().startsWith(label)
  );
}

async function pickChip(filter: string, option: string) {
  await click(document.querySelector('button[aria-label="Add filter"]'));
  await click(await waitFor(() => commandItem(filter), `the ${filter} filter`));
  await click(await waitFor(() => commandItem(option), `the ${option} option`));
}

function setViewportWidth(width: number) {
  Object.defineProperty(window, "innerWidth", { value: width, configurable: true });
  window.matchMedia = ((query: string) => ({
    matches: width < 768,
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
  scopeGame.value = "overwatch";
  permitted = true;
  replace.mockClear();
  setViewportWidth(1280);
  getEncounters.mockReset().mockResolvedValue({
    results: [encounter()],
    total: 1,
    page: 1,
    per_page: 15
  });
  getTournaments.mockReset().mockResolvedValue({
    results: [{ id: 78, name: "OWT 78", discipline: "overwatch" }],
    total: 1,
    page: 1,
    per_page: -1
  });
  getStandings.mockReset().mockResolvedValue([]);
  getTournament.mockReset().mockResolvedValue({
    id: 78,
    name: "OWT 78",
    workspace_id: 4,
    challonge_slug: null
  });
  getStages.mockReset().mockResolvedValue([]);
  window.history.replaceState(null, "", "/admin/matches");
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

describe("/admin/matches", () => {
  it("refuses the whole screen without match.read", async () => {
    permitted = false;
    const container = await mount();

    expect(container.textContent).toContain("No access");
    expect(getEncounters).not.toHaveBeenCalled();
  });

  it("lands on encounters and marks that tab current", async () => {
    const container = await mount();
    await waitFor(() => container.querySelector("table"), "the encounters table");

    expect(tab(container, "Encounters")?.getAttribute("aria-current")).toBe("page");
    // Every view is one link away, and the links carry `?view=`.
    expect(tab(container, "Standings")?.getAttribute("href")).toBe("/admin/matches?view=standings");
    expect(getEncounters).toHaveBeenCalled();
  });

  it("renders the view named by ?view= on load", async () => {
    window.history.replaceState(null, "", "/admin/matches?view=standings&tournament=78");
    const container = await mount();

    await waitFor(() => getStandings.mock.calls.length > 0, "the standings request");
    expect(getStandings.mock.calls[0][0]).toBe(78);
    expect(tab(container, "Standings")?.getAttribute("aria-current")).toBe("page");
    // Standings are computed per tournament, so the encounters list is not
    // fetched for this view at all.
    expect(getEncounters).not.toHaveBeenCalled();
  });

  it("keeps the tournament scope and the Game chip across a view switch and drops the row id", async () => {
    window.history.replaceState(null, "", "/admin/matches?view=encounters&tournament=78&discipline=overwatch&id=8812");
    const container = await mount();
    await waitFor(() => container.querySelector("table"), "the encounters table");

    const href = tab(container, "Parsed maps")?.getAttribute("href") ?? "";
    const params = new URLSearchParams(href.split("?")[1] ?? "");
    expect(params.get("view")).toBe("parsed");
    expect(params.get("tournament")).toBe("78");
    // The encounters and parsed views share one Game chip.
    expect(params.get("discipline")).toBe("overwatch");
    // A row id from the encounters view would select a different entity here.
    expect(params.get("id")).toBeNull();
  });

  it("leaves the tournament chip removable, unlike the same browser in a hub", async () => {
    window.history.replaceState(null, "", "/admin/matches?tournament=78");
    const container = await mount();
    await waitFor(() => container.querySelector("table"), "the encounters table");

    const chip = document.querySelector<HTMLButtonElement>(
      'button[aria-label^="Remove filter Tournament:"]'
    );
    expect(chip).not.toBeNull();

    await click(chip);
    expect(new URLSearchParams(window.location.search).get("tournament")).toBeNull();
  });

  it("renders rows as cards below md, where nine columns do not fit", async () => {
    setViewportWidth(375);
    const container = await mount();
    const cards = await waitFor(
      () => {
        const list = container.querySelectorAll("ul[aria-label='Rows'] > li");
        return list.length > 0 ? list : null;
      },
      "the mobile cards"
    );

    expect(container.querySelector("table")).toBeNull();
    expect(cards[0].textContent).toContain("Team C vs Team D");
    // The card is chosen, not the first three columns: the score and the log
    // state are what a phone needs from an encounter.
    expect(cards[0].textContent).toContain("1–2");
    expect(cards[0].querySelector('[role="img"][aria-label="No logs"]')).not.toBeNull();
  });

  it("names each card's game below md under all games, where the Game column is not shown", async () => {
    scopeGame.value = null;
    getEncounters.mockResolvedValue({ results: [encounter({ discipline: "lol" })], total: 1, page: 1, per_page: 15 });
    setViewportWidth(375);
    const container = await mount();
    const card = await waitFor(() => container.querySelector("ul[aria-label='Rows'] > li"), "the mobile card");

    expect(card.textContent).toContain("Team C vs Team D");
    expect(card.textContent).toContain("League of Legends");
  });

  it("asks the encounters view for the game in scope", async () => {
    scopeGame.value = "lol";
    const container = await mount();
    await waitFor(() => container.querySelector("table"), "the encounters table");

    expect(getEncounters.mock.calls.at(-1)?.[7]).toMatchObject({ discipline: "lol" });
  });

  it("applies the tournament and stage chips under all games", async () => {
    scopeGame.value = null;
    window.history.replaceState(null, "", "/admin/matches?tournament=78&stage=5");
    const container = await mount();
    await waitFor(() => container.querySelector("table"), "the encounters table");

    const call = getEncounters.mock.calls.at(-1)!;
    expect(call[2]).toBe(78);
    expect(call[7]).toMatchObject({ stage_id: 5, discipline: null });
    expect(document.querySelector('button[aria-label^="Remove filter Tournament"]')).not.toBeNull();
  });

  it("a Game chip pick in the parsed view drops the map always and another game's tournament scope, and keeps the view", async () => {
    scopeGame.value = null;
    window.history.replaceState(null, "", "/admin/matches?view=parsed&tournament=78&stage=2&map_id=9&unlinked_only=1");
    await mount();
    await waitFor(() => document.querySelector('button[aria-label="Add filter"]'), "the parsed view's filter bar");

    // OWT 78 is an Overwatch tournament: picking its own game keeps it.
    await pickChip("Game", "Overwatch");
    let url = new URLSearchParams(window.location.search);
    expect(url.get("discipline")).toBe("overwatch");
    expect(url.get("tournament")).toBe("78");
    expect(url.get("stage")).toBe("2");
    expect(url.has("map_id")).toBe(false);

    await pickChip("Game", "League of Legends");
    url = new URLSearchParams(window.location.search);
    expect(url.get("view")).toBe("parsed");
    expect(url.get("discipline")).toBe("lol");
    for (const param of ["map_id", "tournament", "stage"]) expect(url.has(param), param).toBe(false);
    expect(url.get("unlinked_only")).toBe("1");
  });
});
