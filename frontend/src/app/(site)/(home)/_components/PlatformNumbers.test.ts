// @vitest-environment happy-dom
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createTranslator, NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, it, vi } from "vitest";

import messages from "@/i18n/messages/en.json";
import { formatterFor } from "@/lib/datetime/formatter";
import { PlatformNumbers } from "./PlatformNumbers";

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: "home.numbers" | "site.kpi") =>
    createTranslator({ locale: "en", messages, namespace })
}));
vi.mock("@/lib/datetime/server", () => ({
  getFormatter: async () => formatterFor("en", "UTC")
}));
vi.mock("@/lib/site/public-data", () => ({
  getPublicWorkspaces: async () => [
    { id: 1, name: "Anakq", icon_url: null },
    { id: 2, name: "Moonrise", icon_url: null }
  ]
}));

const { reads, extra } = vi.hoisted(() => {
  const reads = { totals: true, extras: true };
  // A read besides the totals: it resolves, or fails once a test turns the extras off.
  const extra = <T>(value: T) =>
    reads.extras ? Promise.resolve(value) : Promise.reject(new Error("read down"));
  return { reads, extra };
});

vi.mock("@/services/statistics.service", () => ({
  default: {
    // Older API responses can omit extended aggregates (here hours and days). Zero is still real data.
    getOverallStatistics: async () => {
      if (!reads.totals) throw new Error("statistics down");
      return {
        tournaments: 3,
        players: 1450,
        champions: 232,
        teams: 1738,
        encounters: 0,
        maps: 4913
      };
    },
    // Only what the maps tile reads: the modes' games and the most played map.
    getMaps: () =>
      extra({
        total_games: 10,
        modes: [
          {
            mode: { name: "Control" },
            games: 6,
            maps: [{ map: { name: "Ilios", image_path: null }, games: 6 }]
          },
          {
            mode: { name: "Push" },
            games: 4,
            maps: [{ map: { name: "Colosseo", image_path: null }, games: 4 }]
          }
        ]
      })
  }
}));
vi.mock("@/services/tournament.service", () => ({
  default: { getStartDates: () => extra(["2025-03-01", "2026-05-01", "2026-06-01"]) }
}));
vi.mock("@/services/encounter.service", () => ({
  default: { getOverview: () => extra({ counts: { finals: 65, upsets: 0 } }) }
}));
vi.mock("@/lib/site/discipline-server", () => ({
  loadGameScopeInit: () =>
    extra({ disciplines: [{ code: "overwatch", name: "Overwatch", enabled: true }] })
}));

beforeEach(() => {
  reads.totals = true;
  reads.extras = true;
});

async function renderNumbers() {
  const root = document.createElement("div");
  root.innerHTML = renderToStaticMarkup(
    createElement(
      NextIntlClientProvider,
      { locale: "en", messages, timeZone: "UTC", now: new Date("2026-01-01T00:00:00Z") },
      await PlatformNumbers()
    )
  );
  return root;
}

/** A tile by its label: the `dd` right after the `dt` is its figure. */
function tile(root: HTMLElement, key: keyof typeof messages.site.kpi) {
  return Array.from(root.querySelectorAll("dl > div")).find(
    (row) => row.querySelector("dt")?.textContent === messages.site.kpi[key]
  );
}
const figure = (root: HTMLElement, key: keyof typeof messages.site.kpi) =>
  tile(root, key)?.querySelector("dt + dd")?.textContent;

it("keeps zero counts, counts the public communities and leaves out what the read does not carry", async () => {
  const root = await renderNumbers();

  expect(figure(root, "encounters")).toBe("0");
  expect(figure(root, "players")).toBe("1,450");
  expect(figure(root, "tournaments")).toBe("3");
  expect(figure(root, "communities")).toBe("2");
  expect(tile(root, "hours")).toBeUndefined();

  expect(tile(root, "players")?.textContent).toContain(
    "232 champions — one player in six has won a tournament"
  );
  expect(
    tile(root, "tournaments")?.querySelector("[role=img]")?.getAttribute("aria-label")
  ).toMatch(/^Tournaments per year: 2025: 1, 2026: 2/);
  expect(tile(root, "maps")?.textContent).toContain("Overwatch: most played — Ilios · 6");
  // A zero sub-count is shown too; the average map length needs the hours the read left out.
  expect(tile(root, "encounters")?.textContent).toContain("65finals");
  expect(tile(root, "encounters")?.textContent).toContain("0upsets");
  expect(tile(root, "encounters")?.textContent).not.toContain(messages.home.numbers.avgMap);
});

it("keeps every tile when only the extra reads fail", async () => {
  reads.extras = false;
  const root = await renderNumbers();

  expect(figure(root, "tournaments")).toBe("3");
  expect(figure(root, "maps")).toBe("4,913");
  expect(figure(root, "encounters")).toBe("0");
  expect(root.querySelector("[role=img]")).toBeNull();
  expect(tile(root, "encounters")?.querySelectorAll("dd")).toHaveLength(1);
});

it("is absent when the totals cannot be read", async () => {
  reads.totals = false;
  const root = await renderNumbers();

  expect(root.textContent).toBe("");
});
