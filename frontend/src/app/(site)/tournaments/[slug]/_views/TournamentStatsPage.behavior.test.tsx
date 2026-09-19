// @vitest-environment happy-dom
//
// Statistics is what only exists once matches have been played: which heroes
// were played, and which maps were played. The pool itself is not here — it has
// its own `maps` section, open before the tournament starts.
//
// What is pinned here:
//  1. `?tab=` is the whole tab state — no `?tab=` means heroes, `?tab=maps`
//     means the map table, and choosing a tab writes the URL (never the
//     default, so the canonical link stays clean);
//  2. every map of the pool is a row, INCLUDING one nobody played: the pool is
//     the regulation, so a map missing from it is a different statement from a
//     map that went unpicked, and a table built from match logs alone could not
//     tell them apart. Rows are ordered by plays;
//  3. counts and mean duration come from the tournament's own series, and
//     "matches →" leads to the matches section filtered by that map;
//  4. an empty pool, a failed read and no hero data are different cards, all
//     from `TournamentPageState`.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { Encounter, Match } from "@/types/encounter.types";
import type { MapRead } from "@/types/map.types";
import type { PickBanConfig, Stage, Tournament } from "@/types/tournament.types";

import TournamentStatsPage, { buildMapPlayedCounts } from "./TournamentStatsPage";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const TOURNAMENT_ID = 88;
const WORKSPACE_ID = 3;

const getHeroPlaytime = vi.fn();
const getEncounters = vi.fn();
const listPublicConfigs = vi.fn();
const getAllMaps = vi.fn();
const getStages = vi.fn();

vi.mock("@/services/hero.service", () => ({
  default: { getHeroPlaytime: (...args: unknown[]) => getHeroPlaytime(...args) }
}));
vi.mock("@/services/encounter.service", () => ({
  default: { getAll: (...args: unknown[]) => getEncounters(...args) }
}));
vi.mock("@/services/pickBan.service", () => ({
  default: { listPublicConfigs: (...args: unknown[]) => listPublicConfigs(...args) }
}));
vi.mock("@/services/map.service", () => ({
  default: { getAll: (...args: unknown[]) => getAllMaps(...args) }
}));
vi.mock("@/services/tournament.service", () => ({
  default: { getStages: (...args: unknown[]) => getStages(...args) }
}));

/**
 * The query string the page reads its tab from, and the URL the segment writes.
 * `render` sets `search`; `replaced` records what a tab click asked the router
 * for, which is the only observable half of "state lives in the URL" without a
 * real Next router.
 */
let search = new URLSearchParams();
let replaced: string[] = [];

vi.mock("next/navigation", () => ({
  useSearchParams: () => search,
  usePathname: () => `/tournaments/${TOURNAMENT_ID}/stats`,
  useRouter: () => ({
    replace: (url: string) => replaced.push(url),
    push: (url: string) => replaced.push(url)
  })
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: { href: string; children?: ReactNode } & Record<string, unknown>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  )
}));

/** The optimiser adds nothing to assert here, and its loader wants a real config. */
vi.mock("next/image", () => ({
  default: ({ src, alt }: { src: string; alt?: string }) => (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={typeof src === "string" ? src : ""} alt={alt ?? ""} />
  )
}));

let tournament: Tournament | undefined;
let tournamentIsError = false;

vi.mock("@/hooks/useTournamentClientData", () => ({
  useTournamentQuery: () => ({
    data: tournament,
    isError: tournamentIsError,
    refetch: () => {}
  })
}));

/**
 * Every field spelled out rather than cast into place: `tsconfig.json` excludes
 * test files, so a fixture that lies about its shape type-checks green and
 * feeds the component a hole.
 */
function makeTournament(): Tournament {
  return {
    id: TOURNAMENT_ID,
    created_at: new Date("2025-01-01T00:00:00Z"),
    updated_at: null,
    workspace_id: WORKSPACE_ID,
    name: "Anak Open",
    slug: "anak-open",
    start_date: new Date("2025-02-01T00:00:00Z"),
    end_date: new Date("2025-02-10T00:00:00Z"),
    description: null,
    challonge_id: null,
    challonge_slug: null,
    is_league: false,
    is_finished: true,
    is_hidden: false,
    team_formation: "balancer",
    status: "completed",
    auto_transitions_enabled: false,
    allow_late_registration: false,
    phase_schedule: [],
    win_points: 3,
    draw_points: 1,
    loss_points: 0,
    stages: [],
    participants_count: 60,
    registrations_count: 60,
    teams_count: 10,
    division_grid_version_id: null,
    division_grid_version: null,
    roster_slots_json: null,
    roster_shape: null,
    roster_locked_by_draft: null,
    cover_image_url: null,
    logo_url: null
  };
}

function map(id: number, name: string, gamemode: string, gamemodeId: number): MapRead {
  return {
    id,
    created_at: new Date("2025-01-01T00:00:00Z"),
    updated_at: null,
    name,
    image_path: `/maps/${id}.jpg`,
    gamemode_id: gamemodeId,
    in_competitive: true,
    aliases: [],
    gamemode: {
      id: gamemodeId,
      created_at: new Date("2025-01-01T00:00:00Z"),
      updated_at: null,
      name: gamemode,
      image_path: `/gamemodes/${gamemodeId}.jpg`,
      slug: gamemode.toLowerCase(),
      description: "",
      aliases: []
    }
  };
}

/**
 * Ids deliberately far from 1..n so a lookup that used an array index instead
 * of the map id would line up with nothing.
 */
const KINGS_ROW = map(45, "King's Row", "Hybrid", 2);
const ILIOS = map(37, "Ilios", "Control", 1);
/** In the pool, never picked. Note ② is about this row existing. */
const SURAVASA = map(91, "Suravasa", "Flashpoint", 4);
const MAPS: MapRead[] = [KINGS_ROW, ILIOS, SURAVASA];

function config(overrides: Partial<PickBanConfig>): PickBanConfig {
  return {
    id: 1,
    tournament_id: TOURNAMENT_ID,
    kind: "map",
    stage_id: null,
    round: null,
    mode: "pool",
    first_pick_rule: "higher_seed",
    first_ban_rotation: "alternate",
    turn_timer_seconds: null,
    preset: null,
    sequence: [],
    no_repeat_scope: "none",
    unique_attribute_per_side_per_round: null,
    allow_protect: false,
    item_ids: [],
    slots: [],
    ...overrides
  };
}

function match(id: number, mapId: number, time: number | null): Match {
  return {
    id,
    created_at: new Date("2025-02-02T00:00:00Z"),
    updated_at: null,
    home_team_id: 1,
    away_team_id: 2,
    score: { home: 2, away: 1 },
    time,
    encounter_id: 500,
    map_id: mapId,
    map_index: null,
    log_name: null,
    source: "log_parser",
    code: null,
    map: null,
    home_team: null,
    away_team: null,
    encounter: null
  };
}

/**
 * Only the fields the played-count aggregation reads are meaningful; the rest
 * are the shape the wire has. `matches` is the whole point — the default
 * entity set of the encounters endpoint omits it.
 */
function encounter(matches: Match[]): Encounter {
  return {
    id: 500,
    created_at: new Date("2025-02-02T00:00:00Z"),
    updated_at: null,
    name: "A vs B",
    home_team_id: 1,
    away_team_id: 2,
    score: { home: 2, away: 1 },
    round: 1,
    best_of: 5,
    tournament_id: TOURNAMENT_ID,
    stage_id: 188,
    stage_item_id: null,
    challonge_id: null,
    status: "completed",
    closeness: null,
    has_logs: true,
    result_status: "confirmed",
    scheduled_at: null,
    started_at: null,
    ended_at: null,
    current_map_index: null,
    confirmed_at: null,
    matches,
    home_team: { id: 1, name: "A" } as Encounter["home_team"],
    away_team: { id: 2, name: "B" } as Encounter["away_team"],
    tournament: makeTournament()
  };
}

const STAGE: Stage = { id: 188, name: "Playoff", order: 1 } as Stage;

let container: HTMLDivElement;
let root: Root;
let client: QueryClient;

beforeEach(() => {
  search = new URLSearchParams();
  replaced = [];
  tournament = makeTournament();
  tournamentIsError = false;

  getHeroPlaytime.mockReset().mockResolvedValue({
    results: [
      {
        hero: {
          id: 7,
          created_at: new Date("2025-01-01T00:00:00Z"),
          updated_at: null,
          name: "Reinhardt",
          slug: "reinhardt",
          image_path: "/heroes/reinhardt.png",
          type: "Tank",
          role: "Tank",
          color: "#9a9a9a",
          aliases: []
        },
        playtime: 0.42
      }
    ],
    total: 1,
    page: 1,
    per_page: -1
  });
  getEncounters.mockReset().mockResolvedValue({
    results: [
      encounter([
        match(1, KINGS_ROW.id, 820),
        match(2, KINGS_ROW.id, 600),
        match(3, ILIOS.id, null)
      ])
    ],
    total: 1,
    page: 1,
    per_page: -1
  });
  listPublicConfigs
    .mockReset()
    .mockResolvedValue({ configs: [config({ item_ids: MAPS.map((m) => m.id) })] });
  getAllMaps
    .mockReset()
    .mockResolvedValue({ results: MAPS, total: MAPS.length, page: 1, per_page: -1 });
  getStages.mockReset().mockResolvedValue([STAGE]);

  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  client.clear();
});

/** Let queued promise callbacks and React Query's own scheduling drain. */
async function settle(ticks = 4) {
  for (let i = 0; i < ticks; i += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function render(query?: string) {
  if (query) search = new URLSearchParams(query);
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en}>
          <TournamentStatsPage tournamentId={TOURNAMENT_ID} slug="anak-open" />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await settle();
}

function tabButtons() {
  return [...container.querySelectorAll('[role="radio"]')].map((tab) => ({
    label: tab.textContent,
    selected: tab.getAttribute("aria-checked") === "true"
  }));
}

/** One row of the map table, flattened to what the reader sees. */
function mapRows() {
  return [...container.querySelectorAll("tbody tr")].map((row) => {
    const cells = [...row.querySelectorAll("td")];
    return {
      map: cells[0]?.textContent ?? "",
      thumb: cells[0]?.querySelector("img")?.getAttribute("src") ?? null,
      mode: cells[1]?.textContent ?? "",
      played: cells[2]?.textContent ?? "",
      duration: cells[3]?.textContent ?? "",
      matchesHref: row.querySelector("a")?.getAttribute("href") ?? null
    };
  });
}

describe("the tab is the URL", () => {
  it("opens on heroes when no tab is named", async () => {
    await render();

    expect(tabButtons()).toEqual([
      { label: en.common.heroes, selected: true },
      { label: en.common.maps, selected: false }
    ]);
    expect(container.textContent).toContain("Reinhardt");
    expect(container.querySelector("tbody")).toBeNull();
    expect(getEncounters).not.toHaveBeenCalled();
  });

  it("renders the map table when the URL names it", async () => {
    await render("tab=maps");

    expect(tabButtons()[1]?.selected).toBe(true);
    expect(container.textContent).not.toContain("Reinhardt");
    expect(container.querySelector("tbody")).not.toBeNull();
  });

  it("writes the chosen tab, and clears the parameter for the default", async () => {
    await render();

    const maps = [...container.querySelectorAll('[role="radio"]')][1] as HTMLButtonElement;
    await act(async () => {
      maps.click();
    });
    expect(replaced.at(-1)).toBe(`/tournaments/${TOURNAMENT_ID}/stats?tab=maps`);

    await render("tab=maps");
    const heroes = [...container.querySelectorAll('[role="radio"]')][0] as HTMLButtonElement;
    await act(async () => {
      heroes.click();
    });
    // The default is never written: no `?tab=heroes` in the canonical URL.
    expect(replaced.at(-1)).toBe(`/tournaments/${TOURNAMENT_ID}/stats`);
  });

  it("keeps the sub-tabs reachable on a phone", async () => {
    await render();

    const tablist = container.querySelector('[role="radiogroup"]');
    // `hideOnMobile` would add `hidden sm:inline-flex`, which is exactly how
    // the maps table became unreachable below 640px.
    expect(tablist?.className.split(/\s+/)).not.toContain("hidden");
  });
});

describe("every map of the pool is a row", () => {
  it("orders by plays and keeps an unplayed pool map, with no matches link", async () => {
    await render("tab=maps");

    const rows = mapRows();
    // King's Row twice, Ilios once, Suravasa never.
    expect(rows.map((row) => row.map.trim())).toEqual([
      KINGS_ROW.name,
      ILIOS.name,
      SURAVASA.name
    ]);
    // The picture rides along, so a row is recognisable the way a pool card is.
    expect(rows[0]?.thumb).toBe(`/maps/${KINGS_ROW.id}.jpg`);

    const suravasa = rows[2];
    expect(suravasa?.played).toBe("0");
    expect(suravasa?.duration).toBe("—");
    expect(suravasa?.matchesHref).toBeNull();
  });

  it("counts plays and averages only the durations that exist", async () => {
    await render("tab=maps");

    const [kingsRow, ilios] = mapRows();
    expect(kingsRow?.played).toBe("2");
    // (820 + 600) / 2 = 710s
    expect(kingsRow?.duration).toBe("11:50");
    expect(kingsRow?.mode).toBe("Hybrid");

    // Played once, but the log carried no length: a count without a duration,
    // not a zero-second map.
    expect(ilios?.played).toBe("1");
    expect(ilios?.duration).toBe("—");
  });

  it("leads to the matches section filtered by the map", async () => {
    await render("tab=maps");

    expect(mapRows()[0]?.matchesHref).toBe(`/tournaments/anak-open/matches?map=${KINGS_ROW.id}`);
  });

  it("counts out of the matches section's own read, which asks for the maps", async () => {
    await render("tab=maps");

    // `tournamentEncountersQueryOptions`: every encounter of the tournament
    // (perPage -1) with the `matches` entity, which the endpoint omits unless
    // named. Sharing that entry is what keeps this table from fetching every
    // encounter a second time.
    const [page, query, tournamentId, perPage, , , workspaceId, filters] = getEncounters.mock
      .calls[0] as [number, string, number, number, unknown, unknown, number, { entities: string[] }];
    expect([page, query, tournamentId, perPage, workspaceId]).toEqual([
      1,
      "",
      TOURNAMENT_ID,
      -1,
      WORKSPACE_ID
    ]);
    expect(filters.entities).toContain("matches");
  });

  it("averages only the timed maps", () => {
    expect(buildMapPlayedCounts([encounter([match(1, KINGS_ROW.id, 600)])])[KINGS_ROW.id]).toEqual({
      played: 1,
      avgDurationSec: 600
    });
  });
});

describe("nothing to show", () => {
  it("says the pool is empty rather than printing a headerless table", async () => {
    listPublicConfigs.mockResolvedValue({ configs: [] });

    await render("tab=maps");

    expect(container.textContent).toContain(en.tournamentDetail.stats.maps.emptyTitle);
    expect(container.querySelector("tbody")).toBeNull();
  });

  it("distinguishes a failed pool read from an empty pool", async () => {
    listPublicConfigs.mockRejectedValue(new Error("boom"));

    await render("tab=maps");

    expect(container.textContent).toContain(en.tournamentDetail.pageState.initialError.title);
    expect(container.textContent).not.toContain(en.tournamentDetail.stats.maps.emptyTitle);
  });

  it("distinguishes a failed match read from zero plays", async () => {
    getEncounters.mockRejectedValue(new Error("boom"));

    await render("tab=maps");

    expect(container.textContent).toContain(en.tournamentDetail.pageState.initialError.title);
    expect(container.querySelector("tbody")).toBeNull();
  });

  it("says there is no hero data yet", async () => {
    getHeroPlaytime.mockResolvedValue({ results: [], total: 0, page: 1, per_page: -1 });

    await render();

    expect(container.textContent).toContain(en.tournamentDetail.stats.heroes.emptyTitle);
  });
});
