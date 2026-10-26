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
  getPublicWorkspaces: async () => [{ id: 1 }, { id: 2 }]
}));
const stats = vi.hoisted(() => ({ fail: false }));
vi.mock("@/services/statistics.service", () => ({
  default: {
    // Older API responses can omit extended aggregates. Zero is still real data.
    getOverallStatistics: async () => {
      if (stats.fail) throw new Error("statistics down");
      return { tournaments: 0, players: 1450, teams: 1738, encounters: 0, maps: 4913 };
    }
  }
}));

beforeEach(() => {
  stats.fail = false;
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

it("keeps zero counts, counts the public communities and leaves out what the read does not carry", async () => {
  const root = await renderNumbers();
  const metric = (key: keyof typeof messages.site.kpi) =>
    Array.from(root.querySelectorAll("dl > div"))
      .find((row) => row.querySelector("dt")?.textContent === messages.site.kpi[key])
      ?.querySelector("dd")?.textContent;

  expect(metric("tournaments")).toBe("0");
  expect(metric("encounters")).toBe("0");
  expect(metric("players")).toBe("1,450");
  expect(metric("communities")).toBe("2");
  expect(metric("hours")).toBeUndefined();
});

it("is absent when the totals cannot be read", async () => {
  stats.fail = true;
  const root = await renderNumbers();

  expect(root.textContent).toBe("");
});
