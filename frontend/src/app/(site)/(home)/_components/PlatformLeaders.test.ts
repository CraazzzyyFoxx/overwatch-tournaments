// @vitest-environment happy-dom
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createTranslator, NextIntlClientProvider } from "next-intl";
import { expect, it, vi } from "vitest";

import messages from "@/i18n/messages/en.json";
import { formatterFor } from "@/lib/datetime/formatter";
import { PlatformLeaders } from "./PlatformLeaders";

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: "home.leaders" | "site.kpi") =>
    createTranslator({ locale: "en", messages, namespace })
}));
vi.mock("@/lib/datetime/server", () => ({
  getFormatter: async () => formatterFor("en", "UTC")
}));
vi.mock("./home-data", () => ({
  getPublicWorkspaces: async () => [{ id: 1 }, { id: 2 }]
}));
vi.mock("@/services/statistics.service", () => ({
  default: {
    // Older API responses can omit extended aggregates. Zero is still real data.
    getOverallStatistics: async () => ({
      tournaments: 0,
      players: 1450,
      teams: 1738,
      champions: 229,
      encounters: 0,
      maps: 4913,
      hours: 926
    }),
    getChampions: async () => ({
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
    }),
    getTopWinratePlayers: async () => ({
      page: 1,
      per_page: 20,
      total: 1,
      results: [{ id: 7, name: "Zuuuuuuuuuuz#2690", value: 0.69 }]
    })
  }
}));

it("preserves zero counts and leaderboard boundaries with incomplete API totals", async () => {
  const root = document.createElement("div");
  root.innerHTML = renderToStaticMarkup(
    createElement(
      NextIntlClientProvider,
      { locale: "en", messages, timeZone: "UTC", now: new Date("2026-01-01T00:00:00Z") },
      await PlatformLeaders()
    )
  );
  const metric = (key: keyof typeof messages.site.kpi) =>
    Array.from(root.querySelectorAll("dl > div"))
      .find((row) => row.querySelector("dt")?.textContent === messages.site.kpi[key])
      ?.querySelector("dd")?.textContent;

  expect(metric("tournaments")).toBe("0");
  expect(metric("encounters")).toBe("0");
  expect(metric("days")).toBeUndefined();
  expect(metric("communities")).toBe("2");
  expect(root.querySelector('a[href="/users/Askhay-21578"]')?.textContent).toContain("4×");
  expect(root.querySelector('a[href="/users/Zuuuuuuuuuuz-2690"]')?.textContent).toContain("69.0%");
  expect(root.querySelector('a[href="/users/Oikawa-21544"]')).not.toBeNull();
  expect(root.querySelector('a[href="/users/ch1dan1ch-2938"]')).toBeNull();
});
