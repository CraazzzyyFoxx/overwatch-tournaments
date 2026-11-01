// @vitest-environment happy-dom
import { createElement, type ReactNode } from "react";
import { prerender } from "react-dom/static";
import { createTranslator, NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "@/i18n/messages/ru.json";
import { formatterFor } from "@/lib/datetime/formatter";
import type { MapStatsResponse, PlayerLeaderboardRow, StatRecord } from "@/types/statistics.types";
import { MapsSection } from "./MapsSection";
import { PlayersSection } from "./PlayersSection";
import { RecordsSection } from "./RecordsSection";

const reads = vi.hoisted(() => ({ getPlayers: vi.fn(), getRecords: vi.fn(), getMaps: vi.fn() }));

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "ru", messages, namespace: namespace as never })
}));
vi.mock("@/lib/datetime/server", () => ({ getFormatter: async () => formatterFor("ru", "UTC") }));
vi.mock("@/lib/site/tenant-host", () => ({ isTenantHost: async () => false }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: () => undefined, push: () => undefined, refresh: () => undefined }),
  usePathname: () => "/statistics",
  useSearchParams: () => new URLSearchParams()
}));
vi.mock("@/services/statistics.service", () => ({ default: reads }));

async function render(node: ReactNode): Promise<HTMLElement> {
  const { prelude } = await prerender(
    createElement(NextIntlClientProvider, { locale: "ru", messages, timeZone: "UTC" }, node)
  );
  const root = document.createElement("div");
  root.innerHTML = await new Response(prelude).text();
  return root;
}

/** ICU separators (narrow no-break spaces) read as plain spaces. */
const text = (root: HTMLElement) => (root.textContent ?? "").replace(/[\u00a0\u202f]/g, " ");

const row = (patch: Partial<PlayerLeaderboardRow>): PlayerLeaderboardRow => ({
  rank: 1,
  id: 1,
  display: { name: "Fox", tag: "#2130", canonical: "Fox#2130", snapshot: null },
  titles: 4,
  tournaments: 20,
  maps_won: 120,
  maps_lost: 40,
  winrate: 0.75,
  low_sample: false,
  ...patch
});

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

describe("statistics almanac sections", () => {
  beforeEach(() => {
    reads.getPlayers.mockReset();
    reads.getRecords.mockReset();
    reads.getMaps.mockReset();
  });

  it("ranks players with medals, the real rank past them and greyed low-sample win rates", async () => {
    reads.getPlayers.mockResolvedValue({
      page: 1,
      per_page: 20,
      total: 2,
      results: [
        row({}),
        row({ rank: 4, id: 2, display: { name: "Newbie", tag: null, canonical: "Newbie", snapshot: null }, titles: 0, tournaments: 2, low_sample: true })
      ]
    });
    const root = await render(
      await PlayersSection({
        discipline: null,
        urlDiscipline: undefined,
        params: { sort: "titles", query: "", page: 1 }
      })
    );

    expect(text(root)).toContain("Fox#2130");
    expect(text(root)).toContain("#4");
    expect(text(root)).toContain("120–40");
    expect(root.querySelector('a[href="/users/Fox-2130"]')).not.toBeNull();
    expect(root.querySelector('th[aria-sort="descending"]')?.textContent).toBe(messages.statistics.players.col.titles);
    expect(root.querySelector('a[href="/statistics?sort=maps_won"]')).not.toBeNull();
    expect(root.querySelector(`[title="${messages.statistics.players.lowSample}"]`)).not.toBeNull();
  });

  it("says a search matched nobody instead of an empty table", async () => {
    reads.getPlayers.mockResolvedValue({ page: 1, per_page: 20, total: 0, results: [] });
    const root = await render(
      await PlayersSection({ discipline: "overwatch", urlDiscipline: "overwatch", params: { sort: "winrate", query: "zz", page: 1 } })
    );
    expect(root.querySelector("table")).toBeNull();
    expect(text(root)).toContain(messages.statistics.players.notFoundTitle);
  });

  it("formats each record and links where it happened", async () => {
    reads.getRecords.mockResolvedValue({
      records: [
        record({
          code: "biggest_upset",
          value: 412,
          relative: 0.18,
          team: { id: 1, name: "Underdogs" },
          opponent: { id: 2, name: "Favourites" },
          score: [3, 1],
          encounter_id: 77,
          tournament: { id: 5, name: "Cup #5" }
        }),
        record({
          code: "hero_damage",
          value: 18532.4,
          player: { id: 3, display: { name: "Fox", tag: "#2130", canonical: "Fox#2130", snapshot: null } },
          team: { id: 1, name: "Underdogs" },
          opponent: { id: 2, name: "Favourites" },
          map: { id: 8, name: "Ilios", slug: "ilios", image_path: null },
          match_id: 9,
          encounter_id: 77
        }),
        record({ code: "longest_map", value: 1263 })
      ]
    });
    const root = await render(await RecordsSection({ discipline: "overwatch" }));

    expect(text(root)).toContain("−412 SR");
    expect(root.querySelector('a[href="/encounters/77"]')?.textContent).toBe("3:1");
    expect(root.querySelector('a[href="/tournaments/5"]')).not.toBeNull();
    expect(text(root)).toContain("18 532");
    expect(root.querySelector('a[href="/matches/9"]')?.textContent).toBe("Ilios");
    expect(root.querySelector('a[href="/users/Fox-2130"]')?.textContent).toBe("Fox#2130");
    expect(text(root)).toContain("21:03");
  });

  it("groups maps by mode with their share, and a dash for an untimed map", async () => {
    const maps: MapStatsResponse = {
      total_games: 12,
      modes: [
        {
          mode: { id: 1, name: "Control", slug: "control", image_path: null },
          games: 10,
          maps: [
            { map: { id: 8, name: "Ilios", slug: "ilios", image_path: null }, games: 6, share: 0.6, avg_duration_s: 612 },
            { map: { id: 9, name: "Oasis", slug: "oasis", image_path: null }, games: 4, share: 0.4, avg_duration_s: null }
          ]
        },
        { mode: null, games: 2, maps: [{ map: { id: 10, name: "Arena", slug: "arena", image_path: null }, games: 2, share: 1, avg_duration_s: 300 }] }
      ]
    };
    reads.getMaps.mockResolvedValue(maps);
    const root = await render(await MapsSection({ discipline: "overwatch" }));

    expect(text(root)).toContain("Control");
    expect(text(root)).toContain("60,0 %");
    expect(text(root)).toContain("10:12");
    expect(text(root)).toContain("—");
    expect(text(root)).toContain(messages.statistics.maps.noMode);
  });

  it("shows a load error, not an empty state, when a read fails", async () => {
    reads.getRecords.mockRejectedValue(new Error("404"));
    const root = await render(await RecordsSection({ discipline: null }));
    expect(root.querySelector('[role="status"]')).not.toBeNull();
    expect(text(root)).toContain(messages.site.state.notEmpty);
  });
});
