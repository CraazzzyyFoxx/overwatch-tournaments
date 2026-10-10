// @vitest-environment happy-dom
//
// The public tournaments list, after it stopped pulling every row at
// `per_page: -1` and filtering in the browser.
//
// That old shape is the reason each of these is pinned. Filtering client-side
// meant the array on screen WAS the whole truth, so the page could count chips
// from it, write `?q=` per keystroke for free, and slice pages locally. None of
// that survives a server-side list:
//  1. cards are the default view; the toggle is a URL fact (`?view=list`) so a
//     shared link opens in the layout the sender was reading - on a phone the
//     cards win regardless, so the list view ships both layouts;
//  2. the list view no longer paginates — the page owns scroll depth, and a
//     second slice inside the table would hide rows already fetched;
//  3. a filter change is a DIFFERENT list: the pages accumulated for the old
//     filter must be dropped and the next request must start at page 1;
//  4. one request per typed word, not per character — the search box is now two
//     network round-trips (list + facets) per distinct value;
//  5. the chip counts come from the facets endpoint, not from `results.length`:
//     the loaded array only knows the pages fetched so far.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act, useEffect, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { Tournament, TournamentFacets, TournamentStatus } from "@/types/tournament.types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const listTournaments = vi.fn();
const getFacets = vi.fn();
const getOverview = vi.fn();
const getOverallStatistics = vi.fn();

vi.mock("@/services/tournament.service", () => ({
  default: {
    listTournaments: (...args: unknown[]) => listTournaments(...args),
    getFacets: (...args: unknown[]) => getFacets(...args)
  }
}));
vi.mock("@/services/encounter.service", () => ({
  default: { getOverview: (...args: unknown[]) => getOverview(...args) }
}));
vi.mock("@/services/statistics.service", () => ({
  default: { getOverallStatistics: (...args: unknown[]) => getOverallStatistics(...args) }
}));
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (
    selector: (state: { currentWorkspaceId: number; workspaces: { id: number; name: string }[] }) => unknown
  ) => selector({ currentWorkspaceId: 1, workspaces: [{ id: 1, name: "OWT" }] })
}));

/**
 * The router shim: `replace` moves the real `window.location` and forces the
 * tree to re-read it, which is the only part of app-router navigation this page
 * depends on — every filter it owns is a query param.
 */
let rerender: (() => void) | null = null;
const replace = vi.fn((url: string) => {
  window.history.replaceState(null, "", url);
  rerender?.();
});

vi.mock("next/navigation", () => ({
  usePathname: () => "/tournaments",
  useRouter: () => ({ replace, push: replace }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: { href: string; children: ReactNode } & React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  )
}));

import TournamentsClient from "./components/TournamentsClient";
import type { StatsScope } from "@/lib/site/stats-scope";

/**
 * Every field spelled out rather than cast into place: `tsconfig.json` excludes
 * test files, so a fixture that lies about its shape type-checks green and
 * feeds the components a hole.
 */
function tournament(id: number, over: Partial<Tournament> = {}): Tournament {
  return {
    id,
    created_at: new Date("2026-01-01T00:00:00Z"),
    updated_at: new Date("2026-01-02T00:00:00Z"),
    workspace_id: 1,
    name: `Cup ${id}`,
    slug: `cup-${id}`,
    start_date: new Date("2026-02-01T00:00:00Z"),
    end_date: new Date("2026-02-08T00:00:00Z"),
    description: null,
    challonge_id: null,
    challonge_slug: null,
    is_league: false,
    is_finished: false,
    is_hidden: false,
    team_formation: "balancer",
    status: "registration",
    auto_transitions_enabled: false,
    allow_late_registration: false,
    phase_schedule: [],
    win_points: 3,
    draw_points: 1,
    loss_points: 0,
    stages: [],
    participants_count: 30,
    registrations_count: null,
    teams_count: 6,
    division_grid_version_id: null,
    division_grid_version: null,
    roster_slots_json: null,
    roster_shape: null,
    roster_locked_by_draft: null,
    cover_image_url: null,
    logo_url: null,
    ...over
  };
}

/** 24 rows: exactly two pages at the page's `per_page: 12`. */
const POOL = Array.from({ length: 24 }, (_, index) => tournament(100 + index));
/** What `?status=live` matches — deliberately fewer than one page. */
const LIVE_POOL = [tournament(7, { status: "live" }), tournament(8, { status: "live" })];

function facets(over: Partial<TournamentFacets> = {}): TournamentFacets {
  return {
    total: 42,
    live: 3,
    by_status: {
      live: 2,
      playoffs: 1,
      registration: 5,
      check_in: 0,
      completed: 30,
      archived: 4,
      draft: 0
    } as Record<TournamentStatus, number>,
    league: 6,
    standard: 36,
    ...over
  };
}

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

function Harness({ scope }: Readonly<{ scope: StatsScope }>) {
  const [, force] = useState(0);
  // Published from an effect, not during render: writing a module-scope binding
  // while rendering is a side effect the react-compiler rules reject.
  useEffect(() => {
    rerender = () => force((value) => value + 1);
  }, []);
  return <TournamentsClient scope={scope} />;
}

async function mount(search = "", scope: StatsScope = "workspace") {
  window.history.replaceState(null, "", `/tournaments${search}`);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mounted.push({ root, container });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en}>
          <Harness scope={scope} />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await settle();
  return container;
}

async function click(element: Element | null | undefined) {
  expect(element).toBeTruthy();
  await act(async () => {
    element!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await settle(4);
}

const VALUE_SETTER = Object.getOwnPropertyDescriptor(
  window.HTMLInputElement.prototype,
  "value"
)!.set!;

/**
 * A whole word typed at human-impossible speed, in ONE act: the point is that
 * the intermediate values never reach a query key, so they must not be given
 * 300ms each to escape the debounce.
 */
async function typeWord(input: HTMLInputElement, word: string) {
  await act(async () => {
    for (let end = 1; end <= word.length; end += 1) {
      VALUE_SETTER.call(input, word.slice(0, end));
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
  });
}

function radio(name: string) {
  return Array.from(document.querySelectorAll('[role="radio"]')).find((item) =>
    item.textContent?.trim().includes(name)
  );
}

function chip(label: string) {
  return Array.from(document.querySelectorAll(".aqt-filter-chip")).find((button) =>
    button.textContent?.trim().startsWith(label)
  );
}

function chipCount(label: string) {
  return chip(label)?.querySelector(".aqt-count")?.textContent?.trim() ?? null;
}

function cards(container: HTMLElement) {
  return Array.from(container.querySelectorAll("[data-tournament-grid] > li"));
}

function searchInput(container: HTMLElement) {
  return container.querySelector<HTMLInputElement>('input[type="search"]')!;
}

function button(text: string) {
  return Array.from(document.querySelectorAll("button")).find(
    (element) => element.textContent?.trim() === text
  );
}

/** Only the list requests, in call order, with the fields under test. */
function listCalls() {
  return listTournaments.mock.calls.map(([params]) => params as Record<string, unknown>);
}

/**
 * The URLs the page wrote. Only the address matters here: the second argument
 * is `useQueryParams`' own `{ scroll: false }`, which is its contract, not
 * this page's.
 */
function urlsWritten() {
  return replace.mock.calls.map(([url]) => url);
}

beforeEach(() => {
  replace.mockClear();
  listTournaments.mockReset().mockImplementation(
    async ({ page = 1, status }: { page?: number; status?: TournamentStatus }) => {
      const pool = status ? LIVE_POOL : POOL;
      const start = (page - 1) * 12;
      return {
        page,
        per_page: 12,
        total: pool.length,
        results: pool.slice(start, start + 12)
      };
    }
  );
  getFacets.mockReset().mockResolvedValue(facets());
  getOverview.mockReset().mockResolvedValue({
    featured: { live: [] },
    kpis: { live_now_count: 0 }
  });
  getOverallStatistics.mockReset().mockResolvedValue({ players: 1453, teams: 210 });
});

afterEach(() => {
  while (mounted.length) {
    const { root, container } = mounted.pop()!;
    act(() => root.unmount());
    container.remove();
  }
});

describe("tournaments list", () => {
  it("opens on the card grid and asks the server for the first page", async () => {
    const container = await mount();

    expect(cards(container)).toHaveLength(12);
    expect(container.querySelector("table")).toBeNull();
    expect(listCalls()).toEqual([
      expect.objectContaining({
        page: 1,
        perPage: 12,
        sort: "start_date",
        order: "desc",
        workspaceId: 1,
        status: undefined,
        isLeague: undefined,
        query: undefined
      })
    ]);
  });

  it("switches to the list view through the URL, and that view never paginates", async () => {
    const container = await mount();

    await click(radio(en.tournamentsList.view.list));

    expect(urlsWritten()).toContain("/tournaments?view=list");
    expect(container.querySelector("table.tn")).toBeTruthy();
    // The list view ships BOTH layouts and lets the viewport pick: the table is
    // desktop-only (two of its six columns fit on a phone), the grid is the
    // mobile list whatever `?view=` says.
    expect(container.querySelector(".tn-card")?.className).toContain("max-md:hidden");
    expect(container.querySelector("[data-tournament-grid]")?.className).toContain("md:hidden");
    // `DataPagination` renders a labelled `<nav>` as soon as there is more than
    // one page. Nothing on this page may.
    expect(container.querySelector("nav")).toBeNull();
  });

  it("opens straight into the list view from a shared ?view=list link", async () => {
    const container = await mount("?view=list");

    expect(container.querySelector("table.tn")).toBeTruthy();
    expect(container.querySelector("[data-tournament-grid]")?.className).toContain("md:hidden");
    // One footer, under BOTH views: scroll depth belongs to the page, not to
    // whichever layout is rendering the rows.
    expect(container.textContent).toContain("Showing 12 of 24 tournaments");
  });

  it("keeps accumulated pages while scrolling, and drops them when a filter moves", async () => {
    const container = await mount();

    await click(button("Show 12 more"));
    expect(cards(container)).toHaveLength(24);
    // The localized progress line, not the component's English fallback — the
    // only place the nested ICU plural in `footer.progress` gets exercised.
    expect(container.textContent).toContain("Showing 24 of 24 tournaments");
    expect(listCalls().map((call) => call.page)).toEqual([1, 2]);

    await click(chip(en.common.statusBadge.live));

    expect(urlsWritten()).toContain("/tournaments?status=live");
    // 2, not 26: the pages fetched under the previous filter belong to a
    // different list and must not carry over.
    expect(cards(container)).toHaveLength(2);
    expect(listCalls().at(-1)).toMatchObject({ page: 1, status: "live" });
  });

  it("changes layout without re-fetching or losing scroll depth", async () => {
    const container = await mount();

    await click(button("Show 12 more"));
    const requests = listTournaments.mock.calls.length;

    await click(radio(en.tournamentsList.view.list));

    // Layout is not a filter: `view` stays out of the query key, so the two
    // pages already paid for are re-used rather than re-requested.
    expect(container.querySelectorAll("table.tn tbody tr")).toHaveLength(24);
    expect(listTournaments.mock.calls.length).toBe(requests);
  });

  it("issues one request per typed word, not per keystroke", async () => {
    const container = await mount();
    const before = listTournaments.mock.calls.length;
    const facetsBefore = getFacets.mock.calls.length;

    await typeWord(searchInput(container), "spring");
    // Responsive field: the value is local state, so it never waits on a fetch.
    expect(searchInput(container).value).toBe("spring");
    expect(listTournaments.mock.calls.length).toBe(before);

    await settle(2, 400);

    expect(listTournaments.mock.calls.length).toBe(before + 1);
    expect(getFacets.mock.calls.length).toBe(facetsBefore + 1);
    expect(listCalls().at(-1)).toMatchObject({ query: "spring", page: 1 });
    expect(urlsWritten()).toContain("/tournaments?q=spring");
  });

  it("counts the chips from the facets, not from the rows it has loaded", async () => {
    // The list is one short page; every chip number below is bigger than it,
    // so a count read off `results.length` cannot pass.
    listTournaments.mockResolvedValue({ page: 1, per_page: 12, total: 2, results: LIVE_POOL });

    const container = await mount();

    expect(cards(container)).toHaveLength(2);
    expect(chipCount(en.common.all)).toBe("42");
    expect(chipCount(en.common.statusBadge.live)).toBe("2");
    expect(chipCount(en.common.statusBadge.completed)).toBe("30");
    expect(chipCount(en.tournamentsList.filters.standard)).toBe("36");
    expect(chipCount(en.common.league)).toBe("6");
    // The heading states the size of the result set, not the rows on screen.
    expect(container.querySelector("h2")?.parentElement?.textContent).toContain("2 tournaments");
  });

  it("reports live events from the unfiltered facet, not from the loaded rows", async () => {
    const container = await mount();

    // `facets.live` is 3 while the loaded page holds no live tournament at all.
    const label = Array.from(container.querySelectorAll("span")).find(
      (node) => node.textContent?.trim() === en.tournamentsList.hero.liveNow
    );
    expect(label?.closest("div")?.textContent).toContain("3");
  });

  it("says nothing about live events when none are running", async () => {
    // A zero in the hero's most prominent slot advertises an empty site, so the
    // stat is absent rather than zero.
    getFacets.mockResolvedValue(facets({ live: 0 }));

    const container = await mount();

    expect(container.textContent).not.toContain(en.tournamentsList.hero.liveNow);
  });

  it("reads every workspace when the visitor chose all workspaces", async () => {
    const container = await mount("", "all");

    expect(listCalls()).toEqual([expect.objectContaining({ workspaceId: "all" })]);
    expect(getFacets).toHaveBeenCalledWith(expect.objectContaining({ workspaceId: "all" }));
    expect(getOverview).toHaveBeenCalledWith("", {}, "all");
    expect(getOverallStatistics).toHaveBeenCalledWith({ workspaceId: "all" });
    expect(container.textContent).toContain(en.common.scope.all);
  });
});
