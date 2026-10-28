// @vitest-environment happy-dom
//
// Maps is its own section: the POOL, in pictures, and how it was played.
// What is pinned:
//
//  1. a single tournament-wide pool is a mode-grouped grid of map cards;
//  2. per-round pools are one card per round, one row per map of the series,
//     each row naming its mode and showing only its own candidates as strips;
//  3. once maps are played, each strip says how often it came up in THAT slot —
//     counted from completed series only — and a round nobody played says nothing;
//  4. `?stage=` narrows the pool to one stage, and the chips only appear when
//     there is more than one stage to choose between;
//  5. an empty pool and a failed read are different cards, both from
//     `TournamentPageState`.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { catalogMap, catalogMode } from "@/test/catalog";
import type { CatalogEntityRead } from "@/types/catalog.types";
import type { Encounter } from "@/types/encounter.types";
import type { PickBanConfig, Stage, Tournament } from "@/types/tournament.types";

import TournamentMapsPage from "./TournamentMapsPage";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const TOURNAMENT_ID = 88;
/** Only what the page reads: the pool by id and discipline, the encounters by id and workspace. */
const TOURNAMENT = { id: TOURNAMENT_ID, workspace_id: 3, discipline: "overwatch" } as Tournament;

const listPublicConfigs = vi.fn();
const getAllMaps = vi.fn();
const getStages = vi.fn();
const getEncounters = vi.fn();

vi.mock("@/services/pickBan.service", () => ({
  default: { listPublicConfigs: (...args: unknown[]) => listPublicConfigs(...args) }
}));
vi.mock("@/services/catalog.service", () => ({
  default: { list: (...args: unknown[]) => getAllMaps(...args) }
}));
vi.mock("@/services/tournament.service", () => ({
  default: { getStages: (...args: unknown[]) => getStages(...args) }
}));
vi.mock("@/services/encounter.service", () => ({
  default: { getAll: (...args: unknown[]) => getEncounters(...args) }
}));

/**
 * `?stage=` is the whole switcher state; `written` records what a chip asked
 * the router for, which is the observable half of "the filter lives in the URL".
 */
let search = new URLSearchParams();
let written: string[] = [];

vi.mock("@/hooks/useQueryParams", () => ({
  useQueryParams: () => ({
    searchParams: search,
    setParams: (next: Record<string, string | null>) => {
      const params = new URLSearchParams(search);
      for (const [key, value] of Object.entries(next)) {
        if (value === null) params.delete(key);
        else params.set(key, value);
      }
      written.push(params.toString());
      search = params;
    }
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
const SURAVASA = map(91, "Suravasa", "Flashpoint", 4);
const MAPS: CatalogEntityRead[] = [KINGS_ROW, ILIOS, SURAVASA];

const GROUP_ID = 177;
const PLAYOFF_ID = 188;

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

/** A round's own pool: slot mode, one candidate list per map of the series. */
function roundConfig(id: number, stageId: number, round: number, slots: number[][]): PickBanConfig {
  return config({
    id,
    stage_id: stageId,
    round,
    mode: "slots",
    slots: slots.map((candidates, index) => ({
      position: index + 1,
      reserve_item_id: null,
      candidates
    }))
  });
}

const STAGES: Stage[] = [
  { id: GROUP_ID, name: "Group stage", order: 0 } as Stage,
  { id: PLAYOFF_ID, name: "Playoff", order: 1 } as Stage
];

/** Group stage plays Ilios only; the playoff plays King's Row and Suravasa. */
const TWO_STAGE_CONFIGS = [
  config({ item_ids: MAPS.map((m) => m.id) }),
  roundConfig(10, GROUP_ID, 1, [[ILIOS.id]]),
  roundConfig(11, PLAYOFF_ID, -1, [[SURAVASA.id]]),
  roundConfig(12, PLAYOFF_ID, 1, [[KINGS_ROW.id], [SURAVASA.id]])
];

/**
 * A series and the maps it played, `[map id, position in the series]` each —
 * only what the play counts read.
 */
function encounter(
  id: number,
  stageId: number,
  round: number,
  status: string,
  played: [number, number][]
): Encounter {
  return {
    id,
    stage_id: stageId,
    round,
    status,
    matches: played.map(([mapId, mapIndex], index) => ({
      id: id * 10 + index,
      map_id: mapId,
      map_index: mapIndex
    }))
  } as unknown as Encounter;
}

/** The encounters read, as the list endpoint answers it. */
const encounterPage = (results: Encounter[]) => ({
  results,
  total: results.length,
  page: 1,
  per_page: -1
});

let container: HTMLDivElement;
let root: Root;
let client: QueryClient;

beforeEach(() => {
  search = new URLSearchParams();
  written = [];

  listPublicConfigs
    .mockReset()
    .mockResolvedValue({ configs: [config({ item_ids: MAPS.map((m) => m.id) })] });
  getAllMaps
    .mockReset()
    .mockResolvedValue({ results: MAPS, total: MAPS.length, page: 1, per_page: -1 });
  getStages.mockReset().mockResolvedValue(STAGES);
  getEncounters.mockReset().mockResolvedValue(encounterPage([]));

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
          <TournamentMapsPage tournament={TOURNAMENT} />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await settle();
}

/** Every map picture on the page, flattened to what the reader sees. */
function poolCards() {
  return [...container.querySelectorAll("figure")].map((card) => ({
    name: card.getAttribute("title") ?? "",
    thumb: card.querySelector("img")?.getAttribute("src") ?? null
  }));
}

function roundCards() {
  return [...container.querySelectorAll("[data-map-pool-round]")];
}

/**
 * A round card's rows, one per map of the series: the label beside the strips
 * ("Map 1" + mode) and each strip's whole text — its count badge, its name and
 * the screen-reader line saying how often it was played.
 */
function slotRows(card: Element | undefined) {
  const rows = new Set(
    [...(card?.querySelectorAll("figure") ?? [])].map((figure) => figure.parentElement)
  );
  return [...rows].map((row) => ({
    label: row?.previousElementSibling?.textContent ?? "",
    strips: [...(row?.children ?? [])].map((strip) => strip.textContent ?? "")
  }));
}

function stageChips() {
  return [...container.querySelectorAll('[role="group"] button')].map((chip) => ({
    label: chip.textContent ?? "",
    pressed: chip.getAttribute("aria-pressed") === "true"
  }));
}

const slotLabel = (n: number) => en.tournamentDetail.mapPool.slot.replace("{n}", String(n));

describe("the pool, in pictures", () => {
  it("falls back to a mode-grouped grid when there are no rounds to lay out", async () => {
    // A single tournament-wide config: the merged list IS the rule here, so it
    // is the one case the flat grid is drawn at all.
    await render();

    const cards = poolCards();
    // Grouped by game mode, and the groups are ordered by mode name:
    // Control · Flashpoint · Hybrid.
    expect(cards.map((card) => card.name)).toEqual([ILIOS.name, SURAVASA.name, KINGS_ROW.name]);
    expect(cards[0]?.thumb).toBe(`/maps/${ILIOS.id}.jpg`);
    expect(roundCards()).toHaveLength(0);
  });

  it("shows the rounds only, with no merged list above them", async () => {
    listPublicConfigs.mockResolvedValue({ configs: TWO_STAGE_CONFIGS });

    await render();

    // Four strips, one per candidate of the four slots the rounds declare. A
    // merged pool list would add three more nobody plays from.
    expect(poolCards()).toHaveLength(4);
    expect(roundCards()).toHaveLength(3);
  });

  it("gives each round a card with one row per map of the series", async () => {
    listPublicConfigs.mockResolvedValue({
      configs: [
        config({ item_ids: MAPS.map((m) => m.id) }),
        roundConfig(11, PLAYOFF_ID, -1, [[SURAVASA.id]]),
        roundConfig(12, PLAYOFF_ID, 1, [[ILIOS.id], [KINGS_ROW.id, SURAVASA.id]])
      ]
    });

    await render();

    const [upper, lower] = roundCards();
    expect(roundCards()).toHaveLength(2);
    // Upper bracket first, lower after — the order the bracket reads in.
    expect(upper?.textContent).toContain("Round 1");
    expect(upper?.textContent).toContain("Bo2");
    // Each row names its slot and mode and holds only its own candidates; a
    // slot whose candidates disagree on the mode says so.
    expect(slotRows(upper)).toEqual([
      { label: `${slotLabel(1)}Control`, strips: [ILIOS.name] },
      {
        label: `${slotLabel(2)}${en.tournamentDetail.maps.mixedModes}`,
        strips: [KINGS_ROW.name, SURAVASA.name]
      }
    ]);

    expect(lower?.textContent).toContain("LB Round 1");
    expect(slotRows(lower)).toEqual([
      { label: `${slotLabel(1)}Flashpoint`, strips: [SURAVASA.name] }
    ]);
  });
});

describe("how the pool was played", () => {
  beforeEach(() => {
    listPublicConfigs.mockResolvedValue({
      configs: [
        config({ item_ids: MAPS.map((m) => m.id) }),
        roundConfig(11, PLAYOFF_ID, -1, [[SURAVASA.id]]),
        roundConfig(12, PLAYOFF_ID, 1, [
          [KINGS_ROW.id, ILIOS.id],
          [SURAVASA.id, ILIOS.id]
        ])
      ]
    });
  });

  it("says nothing about counts while no series is completed", async () => {
    getEncounters.mockResolvedValue(
      encounterPage([encounter(1, PLAYOFF_ID, 1, "in_progress", [[ILIOS.id, 1]])])
    );

    await render();

    expect(container.textContent).not.toContain("×");
    expect(container.textContent).toContain(en.tournamentDetail.mapPool.rounds.lede);
    expect(container.textContent).not.toContain(en.tournamentDetail.maps.playedLede);
  });

  it("counts each map per slot from completed series, and says which never came up", async () => {
    getEncounters.mockResolvedValue(
      encounterPage([
        encounter(1, PLAYOFF_ID, 1, "completed", [
          [KINGS_ROW.id, 1],
          [SURAVASA.id, 2]
        ]),
        encounter(2, PLAYOFF_ID, 1, "completed", [
          [KINGS_ROW.id, 1],
          [ILIOS.id, 2]
        ]),
        // Still running: its Ilios on map 1 is not a play yet.
        encounter(3, PLAYOFF_ID, 1, "in_progress", [[ILIOS.id, 1]])
      ])
    );

    await render();

    expect(container.textContent).toContain(en.tournamentDetail.maps.playedLede);
    const [upper, lower] = roundCards();
    // Ilios is a candidate of both slots and is counted in each on its own.
    expect(slotRows(upper).map((row) => row.strips)).toEqual([
      [`×2${KINGS_ROW.name}played 2 times`, `${ILIOS.name}not played`],
      [`×1${SURAVASA.name}played once`, `×1${ILIOS.name}played once`]
    ]);
    // Nobody played the lower round, so it carries no verdict at all.
    expect(slotRows(lower).map((row) => row.strips)).toEqual([[SURAVASA.name]]);
  });
});

describe("the stage switcher", () => {
  it("appears only once there is more than one stage to choose between", async () => {
    listPublicConfigs.mockResolvedValue({
      configs: [
        config({ item_ids: MAPS.map((m) => m.id) }),
        roundConfig(12, PLAYOFF_ID, 1, [[KINGS_ROW.id]])
      ]
    });

    await render();

    expect(stageChips()).toEqual([]);
  });

  it("offers the whole tournament and every stage that carries a pool", async () => {
    listPublicConfigs.mockResolvedValue({ configs: TWO_STAGE_CONFIGS });

    await render();

    expect(stageChips()).toEqual([
      { label: `${en.tournamentDetail.mapPool.allStages}3`, pressed: true },
      { label: "Group stage1", pressed: false },
      { label: "Playoff2", pressed: false }
    ]);
  });

  it("narrows the rounds to the chosen stage, through the URL", async () => {
    listPublicConfigs.mockResolvedValue({ configs: TWO_STAGE_CONFIGS });

    await render();
    const group = [...container.querySelectorAll('[role="group"] button')][1] as HTMLButtonElement;
    await act(async () => {
      group.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(written.at(-1)).toBe(`stage=${GROUP_ID}`);

    // The URL is the state, so the narrowed render is what `?stage=` produces.
    await render(`stage=${GROUP_ID}`);

    expect(poolCards().map((card) => card.name)).toEqual([ILIOS.name]);
    expect(roundCards()).toHaveLength(1);
    expect(container.textContent).not.toContain(SURAVASA.name);
    expect(stageChips().find((chip) => chip.pressed)?.label).toBe("Group stage1");
  });

  it("ignores a stage that carries no pool", async () => {
    listPublicConfigs.mockResolvedValue({ configs: TWO_STAGE_CONFIGS });

    await render("stage=999");

    // Falls back to the whole tournament rather than an empty section: every
    // stage's rounds are laid out again.
    expect(roundCards()).toHaveLength(3);
  });
});

describe("nothing to show", () => {
  it("says the pool is empty rather than printing an empty grid", async () => {
    listPublicConfigs.mockResolvedValue({ configs: [] });

    await render();

    expect(container.textContent).toContain(en.tournamentDetail.maps.emptyTitle);
    expect(container.querySelector("figure")).toBeNull();
  });

  it("distinguishes a failed pool read from an empty pool", async () => {
    listPublicConfigs.mockRejectedValue(new Error("boom"));

    await render();

    expect(container.textContent).toContain(en.tournamentDetail.pageState.initialError.title);
    expect(container.textContent).not.toContain(en.tournamentDetail.maps.emptyTitle);
  });
});
