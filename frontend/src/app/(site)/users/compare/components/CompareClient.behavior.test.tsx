// @vitest-environment happy-dom
//
// Hero/map ids in the compare URL must belong to the scoped game (P7 §3.4). A conflicting
// `?left_hero_id=<Overwatch id>&discipline=lol` is named, and no hero comparison is requested or shown.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, hydrateRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import messages from "@/i18n/messages/en.json";
import { ApiError } from "@/lib/api/error";
import { disciplineQueryKeys } from "@/lib/site/discipline-query-keys";
import type { GameScopeInit } from "@/lib/site/discipline-scope";
import type { StatsScope } from "@/lib/site/stats-scope";
import { useScopePillOpen } from "@/components/workspace/scope-pill-store";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { catalogEntity } from "@/test/catalog";
import { navigation } from "@/test/url-navigation";
import { PillPick } from "@/test/pill-pick";
import type { CatalogKind } from "@/types/catalog.types";
import type { DisciplineDescriptor } from "@/types/discipline.types";

import UserComparePage from "../page";
import CompareClient from "./CompareClient";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  getEntity: vi.fn(),
  listEntities: vi.fn(),
  heroCompare: vi.fn(),
  compare: vi.fn(),
  games: [
    { code: "overwatch", name: "Overwatch", short_name: "OW", icon: null, enabled: true, kinds: { character: "Hero", map: "Map", mode: "Mode" } },
    { code: "lol", name: "League of Legends", short_name: "LoL", icon: null, enabled: true, kinds: { character: "Champion", map: "Map" } }
  ]
}));

vi.mock("next/navigation", async () => (await import("@/test/url-navigation")).nextNavigationMock);
// The server's view of the visitor: no saved game (all games), League of Legends picked last.
vi.mock("@/lib/site/tenant-host", () => ({
  resolveStatsScope: async () => "all",
  resolveServerDisciplineScope: async () => ({ stored: "all", lastGame: "lol", axis: "all", hostLockedWorkspaceId: null })
}));
vi.mock("@/services/discipline.service", () => ({
  default: {
    list: async () => mocks.games,
    // The browsed game's per-character vocabulary is what the character comparison requests.
    metadata: async () => ({
      ...(await import("@/test/discipline-metadata")).OW_METADATA,
      stat_defs: [
        { id: 1, code: "eliminations", name: "Eliminations", value_format: "integer", aggregation: "sum", group: null, active: true, sort_order: 1 }
      ]
    })
  }
}));
vi.mock("@/services/catalog.service", () => ({
  default: {
    get: (...args: unknown[]) => mocks.getEntity(...args),
    list: (...args: unknown[]) => mocks.listEntities(...args)
  }
}));
vi.mock("@/services/user.service", () => ({
  default: {
    getUserCharacterCompare: (...args: unknown[]) => mocks.heroCompare(...args),
    getUserCompare: (...args: unknown[]) => mocks.compare(...args),
    search: async () => ({ results: [], total: 0 })
  }
}));
vi.mock("@/services/tournament.service", () => ({
  default: { getAll: async () => ({ results: [], total: 0, page: 1, per_page: -1 }) }
}));

let root: Root;
let container: HTMLDivElement;

async function settle(turns = 8) {
  for (let turn = 0; turn < turns; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

let client: QueryClient;

/** The server render's inputs for a visitor with no saved game. */
const INITIAL: GameScopeInit = {
  stored: "all",
  lastGame: null,
  axis: "all",
  hostLockedWorkspaceId: null,
  disciplines: mocks.games as unknown as DisciplineDescriptor[]
};

async function mount(url: string, scope: StatsScope = "all") {
  navigation.reset(url);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 60_000 } } });
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <QueryClientProvider client={client}>
          <CompareClient scope={scope} initial={INITIAL} />
          <PillPick code="lol" />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  await settle();
}

beforeEach(() => {
  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false
  })) as unknown as typeof window.matchMedia;
  // A tab or pill pick writes the last game and the scope into the store: every test starts from no last game.
  useWorkspaceStore.setState({ gameScope: "all", lastGame: null, hostLockedWorkspaceId: null, currentWorkspaceId: null });
  mocks.getEntity.mockReset();
  mocks.listEntities.mockReset().mockResolvedValue({ results: [], total: 0, page: 1, per_page: -1 });
  mocks.heroCompare.mockReset().mockResolvedValue({ metrics: [], subject: { name: "A" }, baseline: { sample_size: 0 } });
  mocks.compare.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

const HERO_QUERY = "user_id=5&scope=hero&left_hero_id=7";

describe("compare selection", () => {
  it("names a hero that is not in the scoped game and requests no hero comparison", async () => {
    mocks.getEntity.mockRejectedValue(new ApiError(404, [{ msg: "not found" }]));

    await mount(`/users/compare?${HERO_QUERY}&discipline=lol`);

    expect(mocks.getEntity.mock.calls.map((call) => call.slice(0, 3))).toContainEqual(["lol", "character", 7]);
    expect(container.textContent).toContain("That selection is not in this game");
    expect(container.textContent).toContain("League of Legends");
    expect(mocks.heroCompare).not.toHaveBeenCalled();
  });

  it("compares a hero that belongs to the scoped game", async () => {
    mocks.getEntity.mockResolvedValue(catalogEntity({ id: 7, name: "Ana", attrs: { class: "support" } }));

    await mount(`/users/compare?${HERO_QUERY}&discipline=overwatch`);

    expect(mocks.heroCompare).toHaveBeenCalled();
    // The comparison is read in the scoped game, with the hero as the left entity.
    expect(mocks.heroCompare.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({ discipline: "overwatch", leftEntityId: 7 })
    );
    expect(container.textContent).not.toContain("That selection is not in this game");
  });

  describe("another game's cached results", () => {
    const OW_RESULT = {
      metrics: [{ stat: "eliminations", left_value: 1, right_value: 2, delta: -1, delta_percent: -50, better_worse: "worse", higher_is_better: true }],
      subject: { name: "OWSUBJECT" },
      baseline: { sample_size: 5 },
      target: null
    };

    async function showOverwatchResults() {
      mocks.getEntity.mockResolvedValue(catalogEntity({ id: 7, name: "Ana", attrs: { class: "support" } }));
      mocks.heroCompare.mockResolvedValue(OW_RESULT);
      await mount(`/users/compare?${HERO_QUERY}&discipline=overwatch`);
      expect(container.textContent).toContain("OWSUBJECT");
    }

    async function switchToLol() {
      await act(async () => {
        navigation.push(`/users/compare?${HERO_QUERY}&discipline=lol`);
      });
      await settle();
    }

    it("shows none of it while the scoped lookup is pending, and none after it 404s", async () => {
      await showOverwatchResults();
      let reject!: (error: unknown) => void;
      mocks.getEntity.mockReturnValue(new Promise((_, fail) => (reject = fail)));

      await switchToLol();
      expect(container.textContent).not.toContain("OWSUBJECT");

      await act(async () => reject(new ApiError(404, [{ msg: "not found" }])));
      await settle();
      expect(container.textContent).not.toContain("OWSUBJECT");
      expect(container.textContent).toContain("That selection is not in this game");
    });

    it("withholds results on a failed lookup, says so, and retries on request", async () => {
      await showOverwatchResults();
      mocks.getEntity.mockRejectedValue(new Error("boom"));

      await switchToLol();
      expect(container.textContent).not.toContain("OWSUBJECT");
      expect(container.textContent).toContain("Could not check that selection");

      const callsBefore = mocks.getEntity.mock.calls.length;
      mocks.getEntity.mockResolvedValue(catalogEntity({ id: 7, discipline: "lol", name: "Ahri" }));
      const retry = Array.from(container.querySelectorAll("button")).find((button) => button.textContent?.trim() === "Retry");
      expect(retry).toBeTruthy();
      await act(async () => retry!.click());
      await settle();
      expect(mocks.getEntity.mock.calls.length).toBeGreaterThan(callsBefore);
      expect(container.textContent).not.toContain("Could not check that selection");
    });
  });
});

describe("the game of the comparison", () => {
  // The URL's hero and map are the shown game's own: their catalog lookups resolve.
  beforeEach(() => {
    mocks.getEntity.mockImplementation(async (_game: string, kind: CatalogKind, id: number) => catalogEntity({ id, kind }));
  });

  it("names the game it shows under all games, with no tabs of its own; the chip opens the site's switcher", async () => {
    useWorkspaceStore.setState({ lastGame: "lol" });
    useScopePillOpen.setState({ open: false });

    await mount("/users/compare?user_id=5");

    expect(container.querySelector('[role="tab"]')).toBeNull();
    const hint = messages.common.discipline.gameHint.replace("{game}", "League of Legends");
    const chip = [...container.querySelectorAll("button")].find((button) => button.textContent === hint);
    expect(chip).toBeTruthy();
    await act(async () => chip!.click());
    expect(useScopePillOpen.getState().open).toBe(true);
  });

  it("shows no tabs when the scope is a game, and compares in that game", async () => {
    useWorkspaceStore.setState({ gameScope: "lol" });
    mocks.getEntity.mockRejectedValue(new ApiError(404, [{ msg: "not found" }]));

    await mount(`/users/compare?${HERO_QUERY}`);

    expect(container.querySelector('[role="tab"]')).toBeNull();
    expect(mocks.getEntity.mock.calls.map((call) => call.slice(0, 3))).toContainEqual(["lol", "character", 7]);
  });

  it("a game picked in the scope pill drops this page's game-bound ids and keeps the player", async () => {
    await mount("/users/compare?user_id=5&scope=hero&left_hero_id=7&map_id=3&role=tank");

    await act(async () => {
      container.querySelector("[data-pill-pick=lol]")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();

    const url = new URL(navigation.pushes.at(-1)!, "http://x");
    expect(url.searchParams.get("discipline")).toBe("lol");
    expect(url.searchParams.get("user_id")).toBe("5");
    for (const param of ["left_hero_id", "map_id", "role"]) expect(url.searchParams.has(param), param).toBe(false);
    expect(useWorkspaceStore.getState().gameScope).toBe("lol");
  });
});

describe("a game without a division grid", () => {
  beforeEach(() => {
    mocks.compare.mockRejectedValue(
      new ApiError(422, [
        { msg: "division_grid_required: 'lol' needs a division grid of its own with tiers", code: "unprocessable" }
      ])
    );
  });

  it("tells the all-communities view to choose a community instead of the server's refusal", async () => {
    await mount("/users/compare?user_id=5&discipline=lol");

    const notice = container.querySelector('[role="alert"]');
    expect(notice?.textContent).toBe(
      messages.common.discipline.gridMissingAcross.replaceAll("{game}", "League of Legends")
    );
    expect(notice?.querySelector("a")).toBeNull();
    expect(container.textContent).not.toContain("division_grid_required");
  });

  it("names the workspace's missing grid on a workspace", async () => {
    useWorkspaceStore.setState({ currentWorkspaceId: 1 });

    await mount("/users/compare?user_id=5&discipline=lol", "workspace");

    const notice = container.querySelector('[role="alert"]');
    expect(notice?.textContent).toContain(messages.common.discipline.gridMissing);
    expect(notice?.textContent).toContain(
      messages.common.discipline.gridMissingOrganizer.replace("{game}", "League of Legends")
    );
    expect(mocks.compare.mock.calls[0]?.[1]).toEqual(expect.objectContaining({ workspaceId: 1 }));
  });
});

describe("the server render", () => {
  it("names the game it shows under all games, and the browser hydrates it without a mismatch", async () => {
    navigation.reset("/users/compare");
    const page = await UserComparePage();
    // The same tree on both sides; only the query client differs, as one request's and the browser's do.
    const tree = (queryClient: QueryClient) => (
      <NextIntlClientProvider locale="en" messages={messages}>
        <QueryClientProvider client={queryClient}>{page}</QueryClientProvider>
      </NextIntlClientProvider>
    );
    const hint = messages.common.discipline.gameHint.replace("{game}", "League of Legends");
    const html = renderToString(tree(new QueryClient()));
    // The last game the visitor played, and no game tabs of the page's own.
    expect(html).toContain(hint);
    expect(html).not.toContain('role="tablist"');

    // The browser already holds the area's games (the header read them) when the page's boundary hydrates, and its
    // store carries the visitor's cookies.
    client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 60_000 } } });
    client.setQueryData(disciplineQueryKeys.list("all"), mocks.games);
    useWorkspaceStore.setState({ lastGame: "lol" });
    const host = document.body.appendChild(document.createElement("div"));
    host.innerHTML = html.replaceAll("&gt;", ">").replaceAll("&#x27;", "'"); // happy-dom leaves these undecoded in attribute values
    const recoverable: unknown[] = [];
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    let hydrated: Root | undefined;
    await act(async () => {
      hydrated = hydrateRoot(host, tree(client), { onRecoverableError: (error) => void recoverable.push(error) });
    });
    await settle();
    const mismatches = errors.mock.calls.filter((call) => String(call[0]).toLowerCase().includes("hydrat"));
    errors.mockRestore();

    expect(recoverable).toEqual([]);
    expect(mismatches).toEqual([]);
    expect(host.textContent).toContain(hint);
    await act(async () => hydrated?.unmount());
    host.remove();
  });
});
