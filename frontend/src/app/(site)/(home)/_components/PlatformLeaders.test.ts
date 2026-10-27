// @vitest-environment happy-dom
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createTranslator, NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, it, vi } from "vitest";

import messages from "@/i18n/messages/en.json";
import { formatterFor } from "@/lib/datetime/formatter";
import type { PageGameResolution } from "@/lib/site/discipline-scope";
import { LOL_GAME, multiResolution, OW_GAME } from "@/test/game-scope";
import type { StatRecord } from "@/types/statistics.types";
import type { UserProfile } from "@/types/user.types";
import { PlatformLeaders } from "./PlatformLeaders";

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: "home.leaders") =>
    createTranslator({ locale: "en", messages, namespace })
}));
vi.mock("@/lib/datetime/server", () => ({
  getFormatter: async () => formatterFor("en", "UTC")
}));
// A board's load error offers a retry, which refreshes the route.
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: () => undefined }) }));
const reads = vi.hoisted(() => ({
  resolution: null as PageGameResolution | null,
  scope: [] as unknown[][],
  getChampions: vi.fn(),
  getRecords: vi.fn(),
  getUserProfile: vi.fn()
}));
vi.mock("@/lib/site/discipline-server", () => ({
  resolveServerPageGame: async (...args: unknown[]) => {
    reads.scope.push(args);
    return {
      init: { stored: "all", lastGame: null, axis: "all", hostLockedWorkspaceId: null, disciplines: [OW_GAME, LOL_GAME] },
      resolution: reads.resolution
    };
  }
}));
// The invalid/empty notice is the shared client component's own concern.
vi.mock("@/components/workspace/ServerGameScopeNotice", () => ({
  ServerGameScopeNotice: () => "[game notice]"
}));
vi.mock("@/services/statistics.service", () => ({
  default: { getChampions: reads.getChampions, getRecords: reads.getRecords }
}));
vi.mock("@/services/user.service", () => ({ default: { getUserProfile: reads.getUserProfile } }));

const CHAMPIONS = [
  { id: 1, name: "Askhay#21578", value: 4 },
  { id: 2, name: "ToR#22245", value: 3 },
  { id: 3, name: "Katan#21331", value: 3 },
  { id: 4, name: "MiniMe#2864", value: 2 },
  { id: 5, name: "Oikawa#21544", value: 1 },
  { id: 6, name: "ch1dan1ch#2938", value: 1 }
];

/** Askhay's profile names a main character, ToR's none; Katan's cannot be read. */
const PROFILES = {
  1: {
    tournaments_count: 52,
    maps_total: 777,
    most_played_character: { id: 7, name: "Sombra", image_path: "/heroes/sombra.png" }
  },
  2: { tournaments_count: 12, maps_total: 140, most_played_character: null }
} as unknown as Record<number, UserProfile>;

const record = (patch: Partial<StatRecord> & Pick<StatRecord, "code" | "value">): StatRecord => ({
  player: null,
  team: null,
  opponent: null,
  tournament: null,
  encounter_id: null,
  match_id: null,
  map: null,
  score: null,
  duration_s: null,
  started_at: null,
  ended_at: null,
  relative: null,
  of_total: null,
  ...patch
});

/** Three of the four leader records (no longest map), and one the hero feed shows instead. */
const RECORDS = [
  record({ code: "win_streak", value: 14, team: { id: 9, name: "Moonrise" } }),
  record({
    code: "biggest_upset",
    value: 412,
    relative: 0.25,
    team: { id: 9, name: "Moonrise" },
    opponent: { id: 10, name: "Anakq" },
    score: [3, 1],
    encounter_id: 77
  }),
  record({ code: "underdog_champion", value: 12, of_total: 16, team: { id: 9, name: "Moonrise" } }),
  record({
    code: "eliminations",
    value: 58,
    player: { id: 1, name: "Askhay#21578" },
    map: { id: 5, name: "Ilios", slug: "ilios", image_path: "/maps/ilios.png" },
    match_id: 900
  })
];

beforeEach(() => {
  reads.resolution = multiResolution(null);
  reads.scope = [];
  reads.getChampions.mockReset().mockResolvedValue({ page: 1, per_page: 20, total: 6, results: CHAMPIONS });
  reads.getRecords.mockReset().mockResolvedValue({ records: RECORDS });
  reads.getUserProfile.mockReset().mockImplementation(async (id: number) => {
    const found = PROFILES[id];
    if (!found) throw new Error("404");
    return found;
  });
});

async function renderLeaders(discipline?: string) {
  const root = document.createElement("div");
  root.innerHTML = renderToStaticMarkup(
    createElement(
      NextIntlClientProvider,
      { locale: "en", messages, timeZone: "UTC", now: new Date("2026-01-01T00:00:00Z") },
      await PlatformLeaders({ discipline })
    )
  );
  return root;
}

const hrefs = (root: Element) => Array.from(root.querySelectorAll("a"), (link) => link.getAttribute("href"));

it("stands the top three on the podium with their main character and career, and #4–5 under it", async () => {
  const root = await renderLeaders();

  expect(reads.scope).toEqual([["multi", undefined]]);
  // Titles span every game; the profiles are the records' game's (the first installed), read across communities.
  expect(reads.getChampions).toHaveBeenCalledWith(null, { skipWorkspace: true });
  expect(reads.getUserProfile.mock.calls).toEqual([
    [1, OW_GAME.code, "all"],
    [2, OW_GAME.code, "all"],
    [3, OW_GAME.code, "all"]
  ]);

  const [podium, rows] = root.querySelectorAll("ol");
  const places = Array.from(podium.children);
  expect(places.map((place) => place.querySelector("a")?.getAttribute("href"))).toEqual([
    "/users/Askhay-21578",
    "/users/ToR-22245",
    "/users/Katan-21331"
  ]);
  expect(places.map((place) => place.querySelector("[data-count]")?.textContent)).toEqual(["4", "3", "3"]);
  expect(places.map((place) => place.querySelector(".lucide-crown") !== null)).toEqual([true, false, false]);

  expect(places[0].querySelector("img")?.getAttribute("src")).toContain("sombra");
  expect(places[0].textContent).toContain("52 tournaments · 777 maps");
  // No main character: the initial, the career still read.
  expect(places[1].querySelector("img")).toBeNull();
  expect(places[1].querySelector('span[aria-hidden="true"]')?.textContent).toBe("T");
  expect(places[1].textContent).toContain("12 tournaments · 140 maps");
  // A profile that could not be read leaves the initial and no career.
  expect(places[2].querySelector('span[aria-hidden="true"]')?.textContent).toBe("K");
  expect(places[2].textContent).not.toContain("tournaments");

  expect(rows.getAttribute("start")).toBe("4");
  expect(hrefs(rows)).toEqual(["/users/MiniMe-2864", "/users/Oikawa-21544"]);
  expect(rows.textContent).toContain("2×");
  // The bar is scaled to the leader's four titles.
  expect(rows.querySelector('[style*="width"]')?.getAttribute("style")).toContain("width:50%");
  expect(root.querySelector('a[href="/users/ch1dan1ch-2938"]')).toBeNull();
});

it("shows the leader records the read carries, as /statistics writes them", async () => {
  const root = await renderLeaders();

  // The log records need a game: the first installed one under all games.
  expect(reads.getRecords).toHaveBeenCalledWith(OW_GAME.code, { skipWorkspace: true });
  expect(root.textContent).toContain(`${OW_GAME.name} · the best of all time`);
  expect(hrefs(root)).toContain(`/statistics?discipline=${OW_GAME.code}#records`);

  const cards = Array.from(root.querySelectorAll("article"));
  const { code } = messages.statistics.records;
  // In their fixed order; the longest map the read lacks and the hero feed's underdog are left out.
  expect(cards.map((card) => card.querySelector("h4")?.textContent)).toEqual([
    code.win_streak,
    code.biggest_upset,
    code.eliminations
  ]);

  const [streak, upset, eliminations] = cards;
  expect(streak.querySelector("[data-count]")?.textContent).toBe("14");
  expect(streak.textContent).toContain("wins in a row");
  // A pip per series won.
  expect(streak.querySelectorAll('span[aria-hidden="true"] > span')).toHaveLength(14);
  expect(upset.querySelector("[data-count]")?.textContent).toBe("−412 SR");
  expect(upset.textContent).toContain("opponent rated 25% higher");
  expect(hrefs(upset)).toContain("/encounters/77");
  // A map record has the map's still behind it and its holder linked.
  expect(eliminations.querySelector("img")?.getAttribute("src")).toContain("ilios");
  expect(hrefs(eliminations)).toContain("/users/Askhay-21578");
  expect(upset.querySelector("img")).toBeNull();
});

it("reads the game's own titles, records and profiles when the page is on one game", async () => {
  reads.resolution = multiResolution("lol");
  const root = await renderLeaders("lol");

  expect(reads.scope).toEqual([["multi", "lol"]]);
  expect(reads.getChampions).toHaveBeenCalledWith("lol", { skipWorkspace: true });
  expect(reads.getRecords).toHaveBeenCalledWith("lol", { skipWorkspace: true });
  expect(reads.getUserProfile).toHaveBeenCalledWith(1, "lol", "all");
  expect(root.textContent).toContain(`${LOL_GAME.name} ·`);
});

it("keeps the block when a read fails: only that board says so", async () => {
  reads.getChampions.mockRejectedValue(new Error("down"));
  let root = await renderLeaders();

  expect(reads.getUserProfile).not.toHaveBeenCalled();
  expect(root.querySelectorAll('[role="status"]')).toHaveLength(1);
  expect(root.querySelectorAll("article")).toHaveLength(3);

  reads.getChampions.mockResolvedValue({ page: 1, per_page: 20, total: 6, results: CHAMPIONS });
  reads.getRecords.mockRejectedValue(new Error("down"));
  root = await renderLeaders();

  expect(root.querySelector('a[href="/users/Askhay-21578"]')).not.toBeNull();
  expect(root.querySelector("article")).toBeNull();
  expect(root.querySelector('[role="status"]')?.textContent).toContain(messages.statistics.records.what);
});

it("says the records are still to come when the read has none of the leader ones", async () => {
  reads.getRecords.mockResolvedValue({ records: [RECORDS[2]] });
  const root = await renderLeaders();

  expect(root.querySelector("article")).toBeNull();
  expect(root.textContent).toContain(messages.statistics.records.empty);
});

it("shows the notice for an invalid explicit game and reads nothing", async () => {
  reads.resolution = {
    game: { kind: "invalid", requested: "chess", reason: "unknown" },
    pill: { kind: "all" },
    tabs: false,
    scope: "all"
  };
  const root = await renderLeaders("chess");

  expect(reads.getChampions).not.toHaveBeenCalled();
  expect(reads.getRecords).not.toHaveBeenCalled();
  expect(reads.getUserProfile).not.toHaveBeenCalled();
  expect(root.textContent).toContain("[game notice]");
});

it("reads nothing when the games could not be read", async () => {
  reads.resolution = null;
  const root = await renderLeaders();

  expect(reads.getChampions).not.toHaveBeenCalled();
  expect(reads.getRecords).not.toHaveBeenCalled();
  expect(root.querySelector('a[href="/users/Askhay-21578"]')).toBeNull();
});
