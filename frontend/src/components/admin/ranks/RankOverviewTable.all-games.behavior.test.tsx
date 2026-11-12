// @vitest-environment happy-dom
//
// `/admin/ranks` under "all games" (spec §6.8): every enabled game's rows with a game column, the game chip leading
// the bar, role and division-range filters only once a game is picked, and no rank-value sort (the values live on
// different grids).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { RankOverviewTable } from "@/components/admin/ranks/RankOverviewTable";
import type { RankOverviewListParams, RankOverviewRow } from "@/services/workspace-player.service";
import type { DisciplineDescriptor } from "@/types/discipline.types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const OW = {
  code: "overwatch",
  name: "Overwatch",
  short_name: "OW",
  icon: null,
  enabled: true,
  capabilities: { native_rank_collection: true }
} as unknown as DisciplineDescriptor;
const LOL = {
  code: "lol",
  name: "League of Legends",
  short_name: "LoL",
  icon: null,
  enabled: true,
  capabilities: { native_rank_collection: false }
} as unknown as DisciplineDescriptor;

let game: string | null = null;
let invalid = false;
let mobile = false;
const selectScope = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/ranks",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));
vi.mock("next-intl", () => ({
  useTranslations: () => Object.assign((key: string) => key, { has: () => true, rich: (key: string) => key })
}));
vi.mock("@/lib/datetime/client", () => ({
  useFormatter: () => ({ dateTime: (value: Date) => value.toISOString() })
}));
vi.mock("@/hooks/useMobile", () => ({ useIsMobile: () => mobile }));
vi.mock("@/hooks/useCurrentWorkspace", () => ({
  useDivisionGrid: () => ({
    tiers: [
      { number: 1, name: "Bronze", rank_min: 0, rank_max: 999, icon_url: "" },
      { number: 2, name: "Silver", rank_min: 1000, rank_max: null, icon_url: "" }
    ]
  })
}));
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (state: { currentWorkspaceId: number }) => unknown) =>
    selector({ currentWorkspaceId: 7 })
}));
vi.mock("@/hooks/useGameScope", () => ({
  useGameScope: () => ({
    axis: 7,
    games: [OW, LOL],
    resolution: invalid
      ? { game: { kind: "invalid", requested: "chess", reason: "unknown" }, pill: { kind: "all" }, tabs: false, scope: "all" }
      : game === null
        ? { game: { kind: "all" }, pill: { kind: "all" }, tabs: false, scope: "all" }
        : { game: { kind: "game", code: game, source: "scope" }, pill: { kind: "game", code: game, locked: false }, tabs: false, scope: game },
    game: invalid ? null : game,
    isError: false,
    refetch: vi.fn(),
    selectScope,
    selectTab: vi.fn()
  })
}));
vi.mock("@/hooks/useGameDescriptors", () => ({
  useGameDescriptors: () => new Map([[OW.code, OW], [LOL.code, LOL]])
}));
vi.mock("@/hooks/useDisciplineMetadata", async () => {
  const { LOL_METADATA, OW_METADATA } = await import("@/test/discipline-metadata");
  return {
    useDisciplineMetadata: (_axis: unknown, code: string | null) => ({
      data: code === null ? undefined : code === "lol" ? LOL_METADATA : OW_METADATA,
      isError: false,
      refetch: vi.fn()
    })
  };
});

const listRanks = vi.fn();
vi.mock("@/services/workspace-player.service", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    workspacePlayerService: {
      listRanks: (...args: unknown[]) => listRanks(...args),
      listAuthors: async () => ({ authors: [] })
    }
  };
});

const row = (overrides: Partial<RankOverviewRow>): RankOverviewRow => ({
  layer: "canon",
  discipline: "overwatch",
  player_id: 42,
  member_id: 9,
  display_name: "Alice",
  identity: null,
  author_user_id: null,
  author_name: null,
  role: "tank",
  rank_value: 3100,
  division: 1,
  source: null,
  sigma: null,
  delta: null,
  canon_diff: null,
  native_division: null,
  native_tier: null,
  context: null,
  at: "2026-01-02T03:04:05Z",
  ...overrides
});

let container: HTMLElement;
let root: Root;

async function render(search = "") {
  window.history.replaceState(null, "", `/admin/ranks${search}`);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <RankOverviewTable />
      </QueryClientProvider>
    );
  });
  await act(async () => {
    const settled = Promise.withResolvers<void>();
    setTimeout(settled.resolve, 0);
    await settled.promise;
  });
}

const lastParams = () => listRanks.mock.calls.at(-1)?.[1] as RankOverviewListParams;
const header = (text: string) => [...container.querySelectorAll("th")].find((th) => th.textContent?.trim() === text);

/** The filters the bar's picker offers, in order (the i18n mock echoes keys: the trigger is `addFilter`). */
async function offeredFilters() {
  await act(async () => {
    container.querySelector('button[aria-label="addFilter"]')?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  return [...document.querySelectorAll('[cmdk-item=""]')].map((item) => item.textContent);
}

beforeEach(() => {
  game = null;
  invalid = false;
  mobile = false;
  Object.defineProperty(window, "innerWidth", { value: 1280, configurable: true });
  selectScope.mockReset();
  listRanks.mockReset();
  listRanks.mockResolvedValue({
    page: 1,
    per_page: 30,
    total: 2,
    results: [row({}), row({ discipline: "lol", member_id: 10, role: "jungle", rank_value: 1800 })]
  });
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  // The picker's popover is portalled to `body`.
  document.body.innerHTML = "";
});

it("reads every game: no game, role or division range on the wire, even from leftover URL filters", async () => {
  await render("?role=tank&div_min=1");

  expect(lastParams().discipline).toBeUndefined();
  expect(lastParams().role ?? []).toEqual([]);
  expect(lastParams().divMin).toBeUndefined();
  expect(container.querySelector('button[aria-label^="filters.divisions"]')).toBeNull();
});

it("adds a game column and leads the bar with the game chip, without the game-bound filters", async () => {
  await render();

  expect(header("column")).toBeDefined();
  const body = container.querySelector("tbody")?.textContent ?? "";
  expect(body).toContain("League of Legends");
  expect(body).toContain("Overwatch");
  // `column` is the game chip (`common.discipline.column`).
  expect(await offeredFilters()).toEqual(["column", "filters.layer", "filters.differsFromCanon"]);
});

it("offers role and division range once a game is picked", async () => {
  game = "overwatch";
  await render("?discipline=overwatch&role=tank");

  expect(container.querySelector('button[aria-label^="filters.divisions"]')).not.toBeNull();
  expect(await offeredFilters()).toEqual(["column", "filters.layer", "filters.role", "filters.differsFromCanon"]);
  expect(lastParams()).toMatchObject({ discipline: "overwatch", role: ["tank"] });
});

it("offers the rank-value sort only under a game", async () => {
  await render();
  expect(header("columns.rankValue")?.getAttribute("aria-sort")).toBeNull();
  await act(async () => root.unmount());
  container.remove();

  game = "overwatch";
  await render();
  expect(header("columns.rankValue")?.getAttribute("aria-sort")).toBe("none");
  expect(lastParams().discipline).toBe("overwatch");
});

it("never sends a game's rank or division sort left in the URL or a saved view to the all-games read", async () => {
  await render("?sort=rank_value&dir=desc");
  expect(lastParams().sort).toBeUndefined();
  await act(async () => root.unmount());
  container.remove();

  game = "overwatch";
  await render("?sort=rank_value&dir=desc");
  expect(lastParams()).toMatchObject({ sort: "rank_value", order: "desc" });
});

it("recovers from an invalid game to all games without the game-bound filters", async () => {
  invalid = true;
  await render("?discipline=chess&role=tank&div_min=1");

  expect(listRanks).not.toHaveBeenCalled();
  const showAll = [...container.querySelectorAll("button")].find((button) => button.textContent === "showAll");
  await act(async () => showAll?.dispatchEvent(new MouseEvent("click", { bubbles: true })));

  expect(selectScope).toHaveBeenCalledWith("all", { dropParams: ["role", "div_min", "div_max"] });
});

it("names each phone card's game under all games, whatever column order the user saved before the game column", async () => {
  // A desktop column order saved before the game column existed: the table appends `game` after these.
  const stored = new Map([
    [
      "admin-table:/admin/ranks:order",
      JSON.stringify(["display_name", "layer", "author", "role", "rank_value", "division", "source", "canon_diff", "delta", "sigma", "context", "at"])
    ]
  ]);
  // Node's own `localStorage` throws without `--localstorage-file` and happy-dom does not shadow it.
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => stored.get(key) ?? null,
      setItem: (key: string, value: string) => void stored.set(key, value),
      removeItem: (key: string) => void stored.delete(key)
    }
  });
  mobile = true;
  // The kit's table reads the viewport through `matchMedia`, not the mocked hook.
  Object.defineProperty(window, "innerWidth", { value: 375, configurable: true });
  await render();

  const cards = [...container.querySelectorAll("ul > li")].map((card) => card.textContent ?? "");
  expect(cards).toHaveLength(2);
  expect(cards[0]).toContain("Overwatch");
  expect(cards[1]).toContain("League of Legends");
});
