// @vitest-environment happy-dom
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createTranslator, NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, it, vi } from "vitest";

import messages from "@/i18n/messages/en.json";
import { formatterFor } from "@/lib/datetime/formatter";
import type { PageGameResolution } from "@/lib/site/discipline-scope";
import { LOL_GAME, multiResolution, OW_GAME } from "@/test/game-scope";
import { PlatformLeaders } from "./PlatformLeaders";

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: "home.leaders") =>
    createTranslator({ locale: "en", messages, namespace })
}));
vi.mock("@/lib/datetime/server", () => ({
  getFormatter: async () => formatterFor("en", "UTC")
}));
const scope = vi.hoisted(() => ({
  resolution: null as PageGameResolution | null,
  calls: [] as unknown[][],
  champions: [] as unknown[][],
  characters: [] as string[]
}));
vi.mock("@/lib/site/discipline-server", () => ({
  resolveServerPageGame: async (...args: unknown[]) => {
    scope.calls.push(args);
    return {
      init: { stored: "all", lastGame: null, axis: "all", hostLockedWorkspaceId: null, disciplines: [OW_GAME, LOL_GAME] },
      resolution: scope.resolution
    };
  }
}));
// The invalid/empty notice is the shared client component's own concern.
vi.mock("@/components/workspace/ServerGameScopeNotice", () => ({
  ServerGameScopeNotice: () => "[game notice]"
}));
vi.mock("@/services/statistics.service", () => ({
  default: {
    getChampions: async (...args: unknown[]) => {
      scope.champions.push(args);
      return {
        page: 1,
        per_page: 20,
        total: 6,
        results: [
          { id: 1, name: "Askhay#21578", value: 4 },
          { id: 2, name: "ToR#22245", value: 3 },
          { id: 3, name: "Katan#21331", value: 3 },
          { id: 4, name: "MiniMe#2864", value: 3 },
          { id: 5, name: "Oikawa#21544", value: 3 },
          { id: 6, name: "ch1dan1ch#2938", value: 2 }
        ]
      };
    },
    getCharacterPlaytime: async (discipline: string) => {
      scope.characters.push(discipline);
      return {
        page: 1,
        per_page: 5,
        total: 2,
        results: [
          { entity: { id: 11, name: "Kiriko", image_path: null }, playtime: 0.0801 },
          { entity: { id: 12, name: "Ana", image_path: null }, playtime: 0.0774 }
        ]
      };
    }
  }
}));

beforeEach(() => {
  scope.resolution = multiResolution(null);
  scope.calls = [];
  scope.champions = [];
  scope.characters = [];
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

it("shows one cross-game top of titles and, under all games, the first installed game's characters", async () => {
  const root = await renderLeaders();

  expect(scope.calls).toEqual([["multi", undefined]]);
  expect(scope.champions[0]?.[0]).toBeNull();
  expect(scope.characters).toEqual([OW_GAME.code]);
  expect(root.querySelector('a[href="/users/Askhay-21578"]')?.textContent).toContain("4×");
  expect(root.querySelector('a[href="/users/Oikawa-21544"]')).not.toBeNull();
  expect(root.querySelector('a[href="/users/ch1dan1ch-2938"]')).toBeNull();
  // The characters are one game's: the board names it.
  expect(root.textContent).toContain(`${OW_GAME.name} ·`);
  expect(root.textContent).toContain("Kiriko");
  expect(root.textContent).toContain("8.0%");
});

it("reads the game's own boards when the page is on one game", async () => {
  scope.resolution = multiResolution("lol");
  const root = await renderLeaders("lol");

  expect(scope.calls).toEqual([["multi", "lol"]]);
  expect(scope.champions[0]?.[0]).toBe("lol");
  expect(scope.characters).toEqual(["lol"]);
  expect(root.textContent).toContain(`${LOL_GAME.name} ·`);
});

it("shows the notice for an invalid explicit game and reads no board", async () => {
  scope.resolution = {
    game: { kind: "invalid", requested: "chess", reason: "unknown" },
    pill: { kind: "all" },
    tabs: false,
    scope: "all"
  };
  const root = await renderLeaders("chess");

  expect(scope.champions).toEqual([]);
  expect(scope.characters).toEqual([]);
  expect(root.textContent).toContain("[game notice]");
});

it("reads no board when the games could not be read", async () => {
  scope.resolution = null;
  const root = await renderLeaders();

  expect(scope.champions).toEqual([]);
  expect(scope.characters).toEqual([]);
  expect(root.querySelector('a[href="/users/Askhay-21578"]')).toBeNull();
});
