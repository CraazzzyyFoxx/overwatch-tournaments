// @vitest-environment happy-dom
//
// A catalog id in the URL must belong to the scoped game (P7 §3.4): `?hero_id=<Overwatch id>&discipline=lol`
// is a conflicting selection to name, not an Overwatch hero to relabel or rank.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, hydrateRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";

import messages from "@/i18n/messages/en.json";
import { ApiError } from "@/lib/api/error";
import { disciplineQueryKeys } from "@/lib/site/discipline-query-keys";
import type { GameScopeInit } from "@/lib/site/discipline-scope";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { catalogEntity } from "@/test/catalog";
import { disciplineServiceMock, LOL_METADATA, OW_METADATA } from "@/test/discipline-metadata";
import { TEST_LADDER_TIERS } from "@/test/native-ladder";
import { navigation } from "@/test/url-navigation";
import { PillPick } from "@/test/pill-pick";

import HeroesComparePage from "../page";
import HeroLeaderboardContent from "./HeroLeaderboardContent";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  getEntity: vi.fn(),
  listEntities: vi.fn(),
  leaderboard: vi.fn()
}));

vi.mock("next/navigation", async () => (await import("@/test/url-navigation")).nextNavigationMock);
// The server's view of the visitor: no saved game (all games), League of Legends picked last.
vi.mock("@/lib/site/tenant-host", () => ({
  resolveStatsScope: async () => "all",
  resolveServerDisciplineScope: async () => ({ stored: "all", lastGame: "lol", axis: "all", hostLockedWorkspaceId: null })
}));
// Real installed-game fixtures (descriptors + metadata): the comparison slots resolve the browsed game's module.
vi.mock("@/services/discipline.service", async () => (await import("@/test/discipline-metadata")).disciplineServiceMock);
vi.mock("@/services/catalog.service", () => ({
  default: {
    get: (...args: unknown[]) => mocks.getEntity(...args),
    list: (...args: unknown[]) => mocks.listEntities(...args)
  }
}));
vi.mock("@/services/statistics.service", () => ({
  default: { getCharacterLeaderboard: (...args: unknown[]) => mocks.leaderboard(...args) }
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

/** Lets the browsed game's lazily loaded comparison module mount: settles until `done` holds (bounded). */
async function settleUntil(done: () => boolean, deadline = Date.now() + 4000) {
  while (!done() && Date.now() < deadline) await settle(1);
}

let client: QueryClient;

const GAMES = [OW_METADATA.discipline, LOL_METADATA.discipline];

/** The server render's inputs for a visitor with no saved game. */
const INITIAL: GameScopeInit = { stored: "all", lastGame: null, axis: "all", hostLockedWorkspaceId: null, disciplines: GAMES };

async function mount(url: string, keepClient = false) {
  navigation.reset(url);
  if (!keepClient) client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 60_000 } } });
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <QueryClientProvider client={client}>
          <HeroLeaderboardContent scope="all" initial={INITIAL} />
          <PillPick code="lol" />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  await settle();
}

beforeEach(() => {
  useWorkspaceStore.setState({ gameScope: "all", lastGame: null, hostLockedWorkspaceId: null, currentWorkspaceId: null });
  mocks.getEntity.mockReset();
  mocks.listEntities.mockReset().mockResolvedValue({ results: [], total: 0, page: 1, per_page: -1 });
  mocks.leaderboard.mockReset().mockResolvedValue({ results: [], total: 0, page: 1, per_page: -1 });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe("hero leaderboard selection", () => {
  it("names a hero that is not in the scoped game and requests no statistics for it", async () => {
    mocks.getEntity.mockRejectedValue(new ApiError(404, [{ msg: "not found" }]));

    await mount("/users/heroes-compare?hero_id=7&discipline=lol");

    expect(mocks.getEntity.mock.calls[0]?.slice(0, 3)).toEqual(["lol", "character", 7]);
    expect(container.textContent).toContain("That hero is not in this game");
    expect(container.textContent).toContain("League of Legends");
    expect(mocks.leaderboard).not.toHaveBeenCalled();
  });

  it("ranks a hero that belongs to the scoped game", async () => {
    mocks.getEntity.mockResolvedValue(catalogEntity({ id: 7, name: "Ana", attrs: { class: "support" } }));

    await mount("/users/heroes-compare?hero_id=7&discipline=overwatch");
    await settleUntil(
      () =>
        container.textContent!.includes(messages.users.heroesCompare.hero.bestKd) &&
        container.textContent!.includes(messages.users.heroesCompare.table.allPlayers)
    );

    expect(mocks.leaderboard).toHaveBeenCalledTimes(1);
    // The scoped game's statistics route, for the checked entity.
    expect(mocks.leaderboard.mock.calls[0]?.slice(0, 2)).toEqual(["overwatch", 7]);
    expect(container.textContent).not.toContain("That hero is not in this game");
    // Overwatch's module draws the hero card and the board.
    expect(container.textContent).toContain(messages.users.heroesCompare.hero.bestKd);
  });

  it("tells a game without a comparison renderer so, with no Overwatch figures and no read", async () => {
    mocks.getEntity.mockResolvedValue(catalogEntity({ id: 9, discipline: "lol", name: "Ahri", attrs: { class: "support" } }));

    await mount("/users/heroes-compare?hero_id=9&discipline=lol");

    expect(container.textContent).toContain(messages.common.discipline.widgetUnsupported);
    expect(container.textContent).not.toContain(messages.users.heroesCompare.hero.bestKd);
    expect(mocks.leaderboard).not.toHaveBeenCalled();
  });

  it("shows an all-communities player's division crest from the game's native ladder, its tier in the tooltip", async () => {
    const tier = TEST_LADDER_TIERS.find((entry) => entry.number === 4)!;
    const read = disciplineServiceMock.default.metadata;
    const metadata = vi
      .spyOn(disciplineServiceMock.default, "metadata")
      .mockImplementation(async (axis, code) =>
        code === "overwatch" ? { ...OW_METADATA, native_ladder: TEST_LADDER_TIERS } : read(axis, code)
      );
    onTestFinished(() => metadata.mockRestore());
    mocks.getEntity.mockResolvedValue(catalogEntity({ id: 7, name: "Ana", attrs: { class: "support" } }));
    // An all-communities board: every tournament's tier is mapped onto the game's own ladder, so the row names no
    // grid version and the page ships no grids.
    mocks.leaderboard.mockResolvedValue({
      results: [{ ...OW_ROW, div: 4, division_grid_version_id: null }],
      division_grids: [],
      total: 1,
      page: 1,
      per_page: -1
    });

    await mount("/users/heroes-compare?hero_id=7&discipline=overwatch");
    await settleUntil(() => container.textContent!.includes("ow-ranked"));

    const crest = container.querySelector<HTMLElement>(`[title="${tier.name}"]`);
    expect(crest?.querySelector("img")?.getAttribute("alt")).toBe(tier.name);
  });

  it("a game picked in the scope pill drops the picked hero and tournament", async () => {
    mocks.getEntity.mockResolvedValue(catalogEntity({ id: 7, name: "Ana", attrs: { class: "support" } }));
    await mount("/users/heroes-compare?hero_id=7&tournament_id=4");

    await act(async () => {
      container.querySelector("[data-pill-pick=lol]")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();

    const url = new URL(navigation.pushes.at(-1)!, "http://x");
    expect(url.searchParams.get("discipline")).toBe("lol");
    expect(url.searchParams.has("hero_id")).toBe(false);
    expect(url.searchParams.has("tournament_id")).toBe(false);
  });

  it("asks for nothing while the id has not been checked yet", async () => {
    mocks.getEntity.mockReturnValue(new Promise(() => undefined));

    await mount("/users/heroes-compare?hero_id=7&discipline=overwatch");

    expect(mocks.leaderboard).not.toHaveBeenCalled();
  });

  const ownDisplay = (name: string) => ({ name, tag: null, canonical: name, snapshot: null });
  /** One Overwatch row with enough games on the hero to clear the all-time sample floor (5). */
  const OW_ROW = {
    rank: 1, user_id: 1, display: ownDisplay("ow-ranked"), role: null, div: 1, team: null, team_id: null,
    games_played: 12, playtime_seconds: 900, per10_eliminations: 10, per10_healing: 0, per10_deaths: 4,
    per10_damage: 1, per10_final_blows: 1, per10_damage_blocked: 0, per10_solo_kills: 0, per10_obj_kills: 0,
    per10_defensive_assists: 0, per10_offensive_assists: 0, per10_all_damage: 1, per10_damage_taken: 1,
    per10_self_healing: 0, per10_ultimates_used: 0, per10_multikills: 0, per10_env_kills: 0, per10_crit_hits: 0,
    avg_weapon_accuracy: 0.5, avg_crit_accuracy: 0.1, kd: 2, kda: 3
  };
  const ROOKIE = { ...OW_ROW, user_id: 2, display: ownDisplay("ow-rookie"), games_played: 2 };

  describe("the sample floor", () => {
    beforeEach(() => {
      mocks.getEntity.mockResolvedValue(catalogEntity({ id: 7, name: "Ana", attrs: { class: "support" } }));
      mocks.leaderboard.mockResolvedValue({ results: [OW_ROW, ROOKIE], total: 2, page: 1, per_page: -1 });
    });

    it("leaves a player with a game or two off the all-time board, says so, and brings them back on request", async () => {
      await mount("/users/heroes-compare?hero_id=7&discipline=overwatch");
      await settleUntil(() => container.textContent!.includes("ow-ranked"));

      expect(container.textContent).not.toContain("ow-rookie");
      expect(container.textContent).toContain("1 player with fewer than 5 games is hidden.");

      const showAll = [...container.querySelectorAll("button")].find((button) => button.textContent === "Show everyone");
      await act(async () => showAll!.click());
      await settleUntil(() => container.textContent!.includes("ow-rookie"));
      expect(new URL(navigation.replaces.at(-1)!, "http://x").searchParams.get("min_games")).toBe("1");
    });

    it("keeps everyone on one tournament's board, where a handful of games is all anyone has", async () => {
      await mount("/users/heroes-compare?hero_id=7&discipline=overwatch&tournament_id=4");
      await settleUntil(() => container.textContent!.includes("ow-ranked"));

      expect(container.textContent).toContain("ow-rookie");
    });
  });

  it("picks the board's hero from the rail", async () => {
    mocks.listEntities.mockResolvedValue({
      results: [
        catalogEntity({ id: 7, name: "Ana", attrs: { class: "support" } }),
        catalogEntity({ id: 8, name: "Reinhardt", attrs: { class: "tank" } })
      ],
      total: 2,
      page: 1,
      per_page: -1
    });
    await mount("/users/heroes-compare?discipline=overwatch");
    const portrait = () => container.querySelector<HTMLButtonElement>('button[aria-label="Reinhardt"]');
    await settleUntil(() => portrait() !== null);

    await act(async () => portrait()!.click());
    await settle();

    expect(new URL(navigation.replaces.at(-1)!, "http://x").searchParams.get("hero_id")).toBe("8");
  });

  describe("another game's cached results", () => {
    async function showOverwatchResults() {
      mocks.getEntity.mockResolvedValue(catalogEntity({ id: 7, name: "Ana", attrs: { class: "support" } }));
      mocks.leaderboard.mockResolvedValue({ results: [OW_ROW], total: 1, page: 1, per_page: -1 });
      await mount("/users/heroes-compare?hero_id=7&discipline=overwatch");
      await settleUntil(() => container.textContent!.includes("ow-ranked"));
      expect(container.textContent).toContain("ow-ranked");
    }

    async function switchToLol() {
      await act(async () => {
        navigation.push("/users/heroes-compare?hero_id=7&discipline=lol");
      });
      await settle();
    }

    it("shows none of it while the scoped lookup is pending, and none after it 404s", async () => {
      await showOverwatchResults();
      let reject!: (error: unknown) => void;
      mocks.getEntity.mockReturnValue(new Promise((_, fail) => (reject = fail)));

      await switchToLol();
      expect(container.textContent).not.toContain("ow-ranked");

      await act(async () => reject(new ApiError(404, [{ msg: "not found" }])));
      await settle();
      expect(container.textContent).not.toContain("ow-ranked");
      expect(container.textContent).toContain("That hero is not in this game");
    });

    it("withholds results on a failed lookup, says so, and retries on request", async () => {
      await showOverwatchResults();
      mocks.getEntity.mockRejectedValue(new Error("boom"));

      await switchToLol();
      expect(container.textContent).not.toContain("ow-ranked");
      expect(container.textContent).toContain("Could not check that hero");

      const callsBefore = mocks.getEntity.mock.calls.length;
      mocks.getEntity.mockResolvedValue(catalogEntity({ id: 7, discipline: "lol", name: "Ana" }));
      const retry = Array.from(container.querySelectorAll("button")).find((button) => button.textContent?.trim() === "Retry");
      expect(retry).toBeTruthy();
      await act(async () => retry!.click());
      await settle();
      expect(mocks.getEntity.mock.calls.length).toBeGreaterThan(callsBefore);
      expect(container.textContent).not.toContain("Could not check that hero");
    });
  });
});

describe("the server render", () => {
  it("names the game it shows under all games, offering the site's switcher, and hydrates without a mismatch", async () => {
    navigation.reset("/users/heroes-compare");
    const page = await HeroesComparePage();
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
    client.setQueryData(disciplineQueryKeys.list("all"), GAMES);
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
