// @vitest-environment happy-dom
//
// Maps is its own section, it holds the POOL only, and it answers in pictures.
// What is pinned:
//
//  1. every map the pool names is a card with its picture, and nothing about
//     play counts is here — those are a statistic and live in Statistics;
//  2. the per-round pools are a matrix of cards — one row per round, one column
//     per map of the series — because that is how organizers author them;
//  3. `?stage=` narrows BOTH blocks to one stage, and the chips only appear
//     when there is more than one stage to choose between;
//  4. an empty pool and a failed read are different cards, both from
//     `TournamentPageState`.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { MapRead } from "@/types/map.types";
import type { PickBanConfig, Stage } from "@/types/tournament.types";

import TournamentMapsPage from "./TournamentMapsPage";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const TOURNAMENT_ID = 88;
const SLUG = "anak-open";

const listPublicConfigs = vi.fn();
const getAllMaps = vi.fn();
const getStages = vi.fn();

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

/**
 * Every field spelled out rather than cast into place: `tsconfig.json` excludes
 * test files, so a fixture that lies about its shape type-checks green and
 * feeds the component a hole.
 */
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
const SURAVASA = map(91, "Suravasa", "Flashpoint", 4);
const MAPS: MapRead[] = [KINGS_ROW, ILIOS, SURAVASA];

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

/** A round's own pool: slot mode, one candidate list per map of the series. */
function roundConfig(
  id: number,
  stageId: number,
  round: number,
  slots: number[][]
): PickBanConfig {
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
          <TournamentMapsPage tournamentId={TOURNAMENT_ID} slug={SLUG} />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await settle();
}

/** One pool card, flattened to what the reader sees. */
function poolCards() {
  return [...container.querySelectorAll("#map-pool figure")].map((card) => ({
    name: card.querySelector("figcaption")?.textContent ?? "",
    thumb: card.querySelector("img")?.getAttribute("src") ?? null
  }));
}

function stageChips() {
  return [...container.querySelectorAll('[role="group"] button')].map((chip) => ({
    label: chip.textContent ?? "",
    pressed: chip.getAttribute("aria-pressed") === "true"
  }));
}

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
    expect(container.querySelector("[data-map-pool-round]")).toBeNull();
  });

  it("shows the rounds only, with no merged list above them", async () => {
    listPublicConfigs.mockResolvedValue({ configs: TWO_STAGE_CONFIGS });

    await render();

    // Four cards, one per candidate of the four slots the rounds declare. A
    // merged pool list would add three more nobody plays from.
    expect(poolCards()).toHaveLength(4);
    expect(container.querySelectorAll("[data-map-pool-round]")).toHaveLength(3);
  });

  it("says nothing about play counts — those are a statistic", async () => {
    await render();

    expect(container.textContent).not.toContain("×");
    expect(container.textContent).not.toContain(en.tournamentDetail.mapPool.col.played);
    // No link into the matches section either: this is the regulation, not a log.
    expect(container.querySelector("a")).toBeNull();
  });

  it("puts one row per round, with a column per map of the series", async () => {
    listPublicConfigs.mockResolvedValue({
      configs: [
        config({ item_ids: MAPS.map((m) => m.id) }),
        roundConfig(11, PLAYOFF_ID, -1, [[SURAVASA.id]]),
        roundConfig(12, PLAYOFF_ID, 1, [[ILIOS.id], [KINGS_ROW.id]])
      ]
    });

    await render();

    const rows = [...container.querySelectorAll("[data-map-pool-round]")];
    expect(rows).toHaveLength(2);
    // Upper bracket first, lower after — the order the bracket reads in.
    expect(rows[0]?.textContent).toContain("Round 1");
    expect(rows[0]?.textContent).toContain("Bo2");
    expect(rows[0]?.textContent).toContain(en.tournamentDetail.mapPool.slot.replace("{n}", "1"));
    // Only its own candidates: round 1 cannot play Suravasa.
    expect(rows[0]?.textContent).toContain(ILIOS.name);
    expect(rows[0]?.textContent).not.toContain(SURAVASA.name);

    expect(rows[1]?.textContent).toContain("LB Round 1");
    expect(rows[1]?.textContent).toContain(SURAVASA.name);
  });

  it("stays without a round block when a single pool decides the tournament", async () => {
    await render();

    expect(container.querySelector("[data-map-pool-round]")).toBeNull();
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

  it("narrows the pool and the rounds to the chosen stage, through the URL", async () => {
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
    const rows = [...container.querySelectorAll("[data-map-pool-round]")];
    expect(rows).toHaveLength(1);
    expect(rows[0]?.textContent).toContain(ILIOS.name);
    expect(container.textContent).not.toContain(SURAVASA.name);
  });

  it("ignores a stage that carries no pool", async () => {
    listPublicConfigs.mockResolvedValue({ configs: TWO_STAGE_CONFIGS });

    await render("stage=999");

    // Falls back to the whole tournament rather than an empty section: every
    // stage's rounds are laid out again.
    expect(container.querySelectorAll("[data-map-pool-round]")).toHaveLength(3);
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
