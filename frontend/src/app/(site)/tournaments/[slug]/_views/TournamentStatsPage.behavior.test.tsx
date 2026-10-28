// @vitest-environment happy-dom
//
// Statistics is what only exists once matches have been played: the players'
// ranked numbers, the bans, which heroes were played and which maps were played.
//
// What is pinned here:
//  1. `?tab=` is the whole tab state — no `?tab=` means players, and choosing a
//     tab writes the URL (never the default, so the canonical link stays clean);
//  2. the players table is ordered by average place, prints each stat with its
//     own precision, and keeps a rostered player with no stats as a dash row;
//  3. heroes: one card per role, in the role order;
//  4. every map of the pool is a row, INCLUDING one nobody played: the pool is
//     the regulation, so a map missing from it is a different statement from a
//     map that went unpicked. Rows are ordered by plays, counted from completed
//     series only, with picks and bans from the pick-ban outcomes;
//  5. an empty pool, a failed read, no hero data and no bans are different
//     cards, all from `TournamentPageState`.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { Encounter, Match } from "@/types/encounter.types";
import { catalogEntity, catalogMap, catalogMode } from "@/test/catalog";
import type { CatalogEntityRead } from "@/types/catalog.types";
import type { Team } from "@/types/team.types";
import type { PickBanConfig, Stage, Tournament } from "@/types/tournament.types";

import TournamentStatsPage, { buildMapPlayedCounts } from "./TournamentStatsPage";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const TOURNAMENT_ID = 88;
const WORKSPACE_ID = 3;

const getCharacterPlaytime = vi.fn();
const getEncounters = vi.fn();
const listPublicConfigs = vi.fn();
const getAllMaps = vi.fn();
const getStages = vi.fn();
const getPlayerStats = vi.fn();
const getPickBanOutcomes = vi.fn();
const getTeams = vi.fn();

vi.mock("@/services/statistics.service", () => ({
  default: { getCharacterPlaytime: (...args: unknown[]) => getCharacterPlaytime(...args) }
}));
vi.mock(
  "@/services/discipline.service",
  async () => (await import("@/test/discipline-metadata")).disciplineServiceMock
);
vi.mock("@/services/encounter.service", () => ({
  default: { getAll: (...args: unknown[]) => getEncounters(...args) }
}));
vi.mock("@/services/pickBan.service", () => ({
  default: { listPublicConfigs: (...args: unknown[]) => listPublicConfigs(...args) }
}));
vi.mock("@/services/catalog.service", () => ({
  default: { list: (...args: unknown[]) => getAllMaps(...args) }
}));
vi.mock("@/services/tournament.service", () => ({
  default: {
    getStages: (...args: unknown[]) => getStages(...args),
    getPlayerStats: (...args: unknown[]) => getPlayerStats(...args),
    getPickBanOutcomes: (...args: unknown[]) => getPickBanOutcomes(...args)
  }
}));
vi.mock("@/services/team.service", () => ({
  default: { getAll: (...args: unknown[]) => getTeams(...args) }
}));
vi.mock("@/services/draft.service", () => ({
  default: { getTournamentBoard: async () => null }
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
    discipline: "overwatch",
    roster_shape: null,
    roster_locked_by_draft: null,
    cover_image_url: null,
    logo_url: null
  };
}

function map(id: number, name: string, gamemode: string, gamemodeId: number): CatalogEntityRead {
  return catalogMap(
    id,
    { ...catalogMode(gamemodeId, gamemode), image_path: `/gamemodes/${gamemodeId}.jpg` },
    {
      name,
      image_path: `/maps/${id}.jpg`
    }
  );
}

/**
 * Ids deliberately far from 1..n so a lookup that used an array index instead
 * of the map id would line up with nothing.
 */
const KINGS_ROW = map(45, "King's Row", "Hybrid", 2);
const ILIOS = map(37, "Ilios", "Control", 1);
/** In the pool, never picked. Note ② is about this row existing. */
const SURAVASA = map(91, "Suravasa", "Flashpoint", 4);
const MAPS: CatalogEntityRead[] = [KINGS_ROW, ILIOS, SURAVASA];

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
    ruleset: { version: 2, timer_seconds: null, on_timeout: "random_fill", phases: [] },
    item_ids: [],
    slots: [],
    ...overrides
  };
}

function match(id: number, mapId: number, time: number | null): Match {
  return {
    id,
    created_at: "2025-02-02T00:00:00Z",
    updated_at: null,
    played_at: null,
    workspace_id: 1,
    discipline: "overwatch",
    encounter_game_id: null,
    participants: [
      {
        encounter_team_id: 11,
        slot: 1,
        source_position: 0,
        tournament_team_id: 1,
        name: "A",
        result: null,
        team_facts: { score: 2 }
      },
      {
        encounter_team_id: 12,
        slot: 2,
        source_position: 1,
        tournament_team_id: 2,
        name: "B",
        result: null,
        team_facts: { score: 1 }
      }
    ],
    duration_s: time,
    encounter_id: 500,
    map_id: mapId,
    map_index: null,
    log_name: null,
    raw_status: null,
    raw_available: false,
    map: null,
    encounter: null
  };
}

/**
 * Only the fields the played-count aggregation reads are meaningful; the rest
 * are the shape the wire has. `matches` is the whole point — the default
 * entity set of the encounters endpoint omits it.
 */
function encounter(matches: Match[], overrides: Partial<Encounter> = {}): Encounter {
  return {
    id: 500,
    created_at: new Date("2025-02-02T00:00:00Z"),
    updated_at: null,
    name: "A vs B",
    slot_count: 2,
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
    result_source: "series_claim",
    result_version: 1,
    scheduled_at: null,
    started_at: null,
    ended_at: null,
    played_at: null,
    is_live: false,
    is_final: false,
    current_map_index: null,
    confirmed_at: null,
    matches,
    games: [],
    teams: [
      {
        id: 11,
        slot: 1,
        team_id: 1,
        name: "A",
        seed: null,
        score: 2,
        placement: null,
        active: true
      },
      {
        id: 12,
        slot: 2,
        team_id: 2,
        name: "B",
        seed: null,
        score: 1,
        placement: null,
        active: true
      }
    ],
    tournament: makeTournament(),
    ...overrides
  };
}

const STAGE: Stage = { id: 188, name: "Playoff", order: 1 } as Stage;

function makeTeam(id: number, name: string, players: string[]): Team {
  return {
    id,
    created_at: new Date(0),
    updated_at: null,
    name,
    image_url: null,
    avg_sr: 3500,
    total_sr: 17_500,
    captain_id: id * 10,
    tournament_id: TOURNAMENT_ID,
    players: players.map((playerName, index) => ({
      id: id * 100 + index,
      created_at: new Date(0),
      updated_at: null,
      name: playerName,
      rank: 3500,
      division: 3,
      role: { dimension: "player_role", role: "damage" },
      tournament_id: TOURNAMENT_ID,
      user_id: id * 1000 + index,
      team_id: id,
      is_newcomer: false,
      is_newcomer_role: false,
      is_substitution: false,
      related_player_id: null,
      user: null
    })),
    tournament: null,
    placement: null,
    group: null
  };
}

/** Users 1000 and 1001 play for Alpha, 2000 for Beta. */
const TEAMS = [makeTeam(1, "Alpha", ["Kenny", "Lucky"]), makeTeam(2, "Beta", ["Mira"])];

let container: HTMLDivElement;
let root: Root;
let client: QueryClient;

beforeEach(() => {
  search = new URLSearchParams();
  replaced = [];
  tournament = makeTournament();
  tournamentIsError = false;

  getCharacterPlaytime.mockReset().mockResolvedValue({
    results: [
      {
        entity: catalogEntity({
          id: 7,
          kind: "character",
          name: "Reinhardt",
          slug: "reinhardt",
          image_path: "/heroes/reinhardt.png",
          attrs: { class: "tank" }
        }),
        playtime: 0.42
      },
      {
        entity: catalogEntity({
          id: 9,
          kind: "character",
          name: "Ana",
          slug: "ana",
          attrs: { class: "support" }
        }),
        playtime: 0.5
      }
    ],
    total: 2,
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
  getTeams.mockReset().mockResolvedValue({ results: TEAMS, total: 2, page: 1, per_page: -1 });
  // Kenny and Lucky have ranked numbers, Mira none; Lucky leads.
  getPlayerStats.mockReset().mockResolvedValue({
    total_players: 2,
    players: [
      {
        player_id: 1000,
        stats: { performance: { value: 2.4, rank: 2 }, kda: { value: 2.456, rank: 2 } }
      },
      {
        player_id: 1001,
        stats: { performance: { value: 1.8, rank: 1 }, kda: { value: 3.1, rank: 1 } }
      }
    ]
  });
  getPickBanOutcomes.mockReset().mockResolvedValue({ hero_bans: [], map_outcomes: [] });

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
          <TournamentStatsPage slug="anak-open" />
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

/** The table a tab renders, by its accessible name. */
function table(label: string) {
  return container.querySelector(`table[aria-label="${label}"]`);
}

/** One row of the map table, flattened to what the reader sees. Column 0 is the place. */
function mapRows() {
  return [...(table(en.tournamentDetail.stats.maps.table)?.querySelectorAll("tbody tr") ?? [])].map(
    (row) => {
      const cells = [...row.querySelectorAll("td")];
      const [name, mode] = [...(cells[1]?.querySelectorAll(".flex-col > *") ?? [])];
      return {
        map: name?.textContent ?? "",
        thumb: cells[1]?.querySelector("img")?.getAttribute("src") ?? null,
        mode: mode?.textContent ?? "",
        played: cells[2]?.textContent ?? "",
        picked: cells[3]?.textContent ?? "",
        banned: cells[4]?.textContent ?? "",
        duration: cells[5]?.textContent ?? "",
        matchesHref: row.querySelector("a")?.getAttribute("href") ?? null
      };
    }
  );
}

function clickTab(index: number) {
  const tab = [...container.querySelectorAll('[role="radio"]')][index] as HTMLButtonElement;
  return act(async () => {
    tab.click();
  });
}

describe("the tab is the URL", () => {
  it("opens on players when no tab is named, without reading the other tabs", async () => {
    await render();

    const tabs = en.tournamentDetail.stats.tabs;
    expect(tabButtons()).toEqual([
      { label: tabs.players, selected: true },
      { label: tabs.bans, selected: false },
      { label: tabs.heroes, selected: false },
      { label: tabs.maps, selected: false }
    ]);
    expect(table(en.tournamentDetail.stats.players.table)).not.toBeNull();
    expect(getCharacterPlaytime).not.toHaveBeenCalled();
    expect(getEncounters).not.toHaveBeenCalled();
  });

  it("renders the map table when the URL names it", async () => {
    await render("tab=maps");

    expect(tabButtons()[3]?.selected).toBe(true);
    expect(table(en.tournamentDetail.stats.maps.table)).not.toBeNull();
    expect(table(en.tournamentDetail.stats.players.table)).toBeNull();
  });

  it("writes the chosen tab, and clears the parameter for the default", async () => {
    await render();
    await clickTab(3);
    expect(replaced.at(-1)).toBe(`/tournaments/${TOURNAMENT_ID}/stats?tab=maps`);

    await render("tab=maps");
    await clickTab(0);
    // The default is never written: no `?tab=players` in the canonical URL.
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

describe("players", () => {
  it("ranks by average place, with each stat at its precision and a dash where there is none", async () => {
    await render();

    const rows = [
      ...(table(en.tournamentDetail.stats.players.table)?.querySelectorAll("tbody tr") ?? [])
    ].map((row) => [...row.querySelectorAll("td")].map((cell) => cell.textContent));
    // Columns: place, player (name + team), avg place, KDA, …
    expect(rows.map((cells) => cells.slice(1, 4))).toEqual([
      ["LuckyAlpha", "1.80", "3.10"],
      ["KennyAlpha", "2.40", "2.46"],
      // Rostered, never logged: still a row, sorted after everyone ranked.
      ["MiraBeta", "—", "—"]
    ]);
  });
});

describe("heroes", () => {
  it("gives each role its own card, in the role order", async () => {
    await render("tab=heroes");

    const cards = [...container.querySelectorAll("h2")].map((heading) => heading.textContent);
    expect(cards).toEqual([en.tournamentDetail.roles.tank, en.tournamentDetail.roles.support]);
    expect(container.textContent).toContain("Reinhardt");
    // The tournament's own game and workspace, the whole tournament.
    expect(getCharacterPlaytime).toHaveBeenCalledWith(
      "overwatch",
      expect.objectContaining({ axis: WORKSPACE_ID, tournamentId: TOURNAMENT_ID, perPage: -1 })
    );
  });
});

describe("every map of the pool is a row", () => {
  it("orders by plays and keeps an unplayed pool map, with no matches link", async () => {
    await render("tab=maps");

    const rows = mapRows();
    // King's Row twice, Ilios once, Suravasa never.
    expect(rows.map((row) => row.map)).toEqual([KINGS_ROW.name, ILIOS.name, SURAVASA.name]);
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

  it("counts only completed series", async () => {
    getEncounters.mockResolvedValue({
      results: [
        encounter([match(1, KINGS_ROW.id, 820)]),
        // Still being played: its maps are not results yet.
        encounter([match(2, SURAVASA.id, 500), match(3, SURAVASA.id, 500)], {
          id: 501,
          status: "open",
          is_live: true
        })
      ],
      total: 2,
      page: 1,
      per_page: -1
    });

    await render("tab=maps");

    const rows = mapRows();
    expect(rows.map((row) => [row.map, row.played])).toEqual([
      [KINGS_ROW.name, "1"],
      [ILIOS.name, "0"],
      [SURAVASA.name, "0"]
    ]);
  });

  it("shows how often teams picked and struck each map", async () => {
    getPickBanOutcomes.mockResolvedValue({
      hero_bans: [],
      map_outcomes: [
        { encounter_id: 500, map_id: KINGS_ROW.id, picked: true },
        { encounter_id: 501, map_id: KINGS_ROW.id, picked: true },
        { encounter_id: 500, map_id: SURAVASA.id, picked: false },
        { encounter_id: 501, map_id: SURAVASA.id, picked: false },
        { encounter_id: 502, map_id: SURAVASA.id, picked: false }
      ]
    });

    await render("tab=maps");

    expect(mapRows().map((row) => [row.map, row.picked, row.banned])).toEqual([
      [KINGS_ROW.name, "2", "0"],
      [ILIOS.name, "0", "0"],
      [SURAVASA.name, "0", "3"]
    ]);
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
      .calls[0] as [
      number,
      string,
      number,
      number,
      unknown,
      unknown,
      number,
      { entities: string[] }
    ];
    expect([page, query, tournamentId, perPage, workspaceId]).toEqual([
      1,
      "",
      TOURNAMENT_ID,
      -1,
      WORKSPACE_ID
    ]);
    expect(filters.entities).toContain("matches");
  });

  it("averages only the timed maps, across series", () => {
    const counts = buildMapPlayedCounts([
      encounter([match(1, KINGS_ROW.id, 600), match(2, ILIOS.id, null)]),
      encounter([match(3, KINGS_ROW.id, 900), match(4, KINGS_ROW.id, null)], { id: 501 })
    ]);

    expect(counts[KINGS_ROW.id]).toEqual({ played: 3, avgDurationSec: 750 });
    expect(counts[ILIOS.id]).toEqual({ played: 1, avgDurationSec: null });
    expect(counts[SURAVASA.id]).toBeUndefined();
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
    getCharacterPlaytime.mockResolvedValue({ results: [], total: 0, page: 1, per_page: -1 });

    await render("tab=heroes");

    expect(container.textContent).toContain(en.tournamentDetail.stats.heroes.emptyTitle);
  });

  it("says there were no bans when the outcomes cannot be read", async () => {
    getPickBanOutcomes.mockRejectedValue(new Error("boom"));

    await render("tab=bans");

    expect(container.textContent).toContain(en.tournamentDetail.stats.bans.emptyTitle);
  });
});
