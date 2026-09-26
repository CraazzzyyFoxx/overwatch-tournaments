// @vitest-environment happy-dom
//
// Two claims about what a spectator can read off the public standings table:
//
// 1. The "top N advance" cut-line follows the GROUP, not just the stage. The
//    table resolved one number per stage, so a tournament that takes 3 from a
//    strong group and 2 from the rest drew the line in the wrong place for one
//    of them — and tinted the wrong rows as advancing, which is the only signal
//    a spectator has about who is through.
// 2. Ties are visible: rows the engine could not separate share a rank, both
//    Buchholz numbers are printed, and a cluster spanning the cut-line says so.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { Stage, StageItem, Standings } from "@/types/tournament.types";

import StandingsTable from "./StandingsTable";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("@/services/tournament.service", () => ({
  default: { getStages: vi.fn().mockResolvedValue([]) }
}));

function groupItem(id: number, advance: number | null): StageItem {
  return {
    id,
    stage_id: 7,
    name: `Group ${id}`,
    type: "group",
    order: 0,
    advance_count: advance,
    inputs: []
  };
}

function stage(items: StageItem[]): Stage {
  return {
    id: 7,
    tournament_id: 1,
    name: "Groups",
    description: null,
    stage_type: "round_robin",
    max_rounds: 3,
    advance_count: 2,
    split_lower_bracket: false,
    order: 0,
    is_active: true,
    is_published: true,
    is_completed: false,
    ranking_preset: null,
    tiebreak_order: null,
    scoring: { win: null, draw: null, loss: null },
    swiss_bye_points: null,
    de_grand_final_type: "no_reset",
    seed_ranking: "slot",
    best_of: { default: 3, by_round: {}, final: null },
    ffa_scoring: { placement_points: [], score_points: 1, score_label: null },
    challonge_id: null,
    challonge_slug: null,
    items
  };
}

function standing(
  position: number,
  item: StageItem,
  source: Stage,
  extra: Partial<Standings> = {}
): Standings {
  return {
    id: position,
    tournament_id: 1,
    team_id: position,
    stage_id: source.id,
    stage_item_id: item.id,
    position,
    overall_position: position,
    matches: 3,
    win: 2,
    draw: 0,
    lose: 1,
    points: 2,
    buchholz: null,
    full_buchholz: null,
    tie_group: null,
    is_pinned: false,
    tb: null,
    score_differential: null,
    ranking_context: null,
    tb_metrics: null,
    source_rule_profile: null,
    tiebreak_order: null,
    team: null,
    tournament: null,
    stage: source,
    stage_item: item,
    matches_history: [],
    ...extra
  };
}

let container: HTMLDivElement;
let root: Root;

async function mount(standings: Standings[], stages: Stage[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider client={client}>
          <StandingsTable standings={standings} stages={stages} is_groups />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
}

/** The 1-based row the dashed cut-line sits under, or 0 when there is none. */
function cutAfterRow() {
  const rows = [...container.querySelectorAll("tbody tr")];
  return rows.findIndex((row) => row.querySelector(".st-cut") != null);
}

function advancingRanks() {
  return [...container.querySelectorAll("tbody tr.advance .st-rank")].map((node) =>
    Number(node.textContent)
  );
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

describe("standings cut-line", () => {
  it("draws the stage's number for a group that sets none", async () => {
    const override = groupItem(100, 3);
    const inherits = groupItem(101, null);
    const groups = stage([override, inherits]);

    await mount(
      [1, 2, 3, 4].map((position) => standing(position, inherits, groups)),
      [groups]
    );

    expect(advancingRanks()).toEqual([1, 2]);
    expect(cutAfterRow()).toBe(2);
  });

  it("draws the group's own number when it overrides the stage", async () => {
    const override = groupItem(100, 3);
    const groups = stage([override, groupItem(101, null)]);

    await mount(
      [1, 2, 3, 4].map((position) => standing(position, override, groups)),
      [groups]
    );

    expect(advancingRanks()).toEqual([1, 2, 3]);
    expect(cutAfterRow()).toBe(3);
  });
});

describe("standings tie visibility", () => {
  it("prints median and full Buchholz, and the median alone when full is missing", async () => {
    const group = groupItem(101, null);
    const groups = stage([group]);

    await mount(
      [
        standing(1, group, groups, { buchholz: 9, full_buchholz: 15 }),
        standing(2, group, groups, { buchholz: 9, full_buchholz: null }),
        standing(3, group, groups, { buchholz: null, full_buchholz: 12 })
      ],
      [groups]
    );

    // Buchholz is the 6th cell: #, team, W·D·L, Pts, H2H, Buchholz. Only the
    // team rows carry a rank — the cut-line and its warning are single-cell.
    const cells = [...container.querySelectorAll("tbody tr")]
      .filter((row) => row.querySelector(".st-rank") != null)
      .map((row) => row.children[5]?.textContent ?? "");

    expect(cells).toEqual(["9.0 · 15.0", "9.0", "—"]);
  });

  it("gives a tie cluster one shared rank and leaves the next row its own", async () => {
    // advance_count 3, so the cluster sits wholly above the cut-line.
    const group = groupItem(100, 3);
    const groups = stage([group, groupItem(101, null)]);

    await mount(
      [
        standing(1, group, groups),
        standing(2, group, groups, { tie_group: 2 }),
        standing(3, group, groups, { tie_group: 2 }),
        standing(4, group, groups),
        standing(5, group, groups)
      ],
      [groups]
    );

    const ranks = [...container.querySelectorAll("tbody .st-rank")].map((node) => node.textContent);

    expect(ranks).toEqual(["1", "2", "2", "4", "5"]);
    expect(container.querySelector("tbody tr.tie")).toBeNull();
  });

  it("marks the rows a cut-line splits as TIE instead of promising them through", async () => {
    // Inherits the stage's advance_count of 2, so positions 2 and 3 — one
    // cluster — land on opposite sides of the line.
    const group = groupItem(101, null);
    const groups = stage([group]);

    await mount(
      [
        standing(1, group, groups),
        standing(2, group, groups, { tie_group: 2 }),
        standing(3, group, groups, { tie_group: 2 }),
        standing(4, group, groups)
      ],
      [groups]
    );

    const tied = [...container.querySelectorAll("tbody tr.tie")];
    expect(tied).toHaveLength(2);
    // The row above the line would have said "Adv" — a promise the results
    // never made, since the assigned order is what puts it there.
    expect(tied.map((row) => row.querySelector(".st-status")?.textContent)).toEqual([
      en.standings.tieStatus,
      en.standings.tieStatus
    ]);
    expect(tied[0].querySelector(".st-status")?.getAttribute("title")).toBe(
      en.standings.tieDecidesAdvance
    );
  });
});

describe("upper vs lower bracket boundary", () => {
  function splitPlayoff(items: StageItem[] = []): Stage {
    return {
      ...stage(items),
      id: 8,
      name: "Playoffs",
      stage_type: "double_elimination",
      advance_count: null,
      split_lower_bracket: true,
      order: 1
    };
  }

  it("draws the split inside the advancing block and warns when a tie spans it", async () => {
    // The real shape this was reported on: 4 advance, the playoff splits them
    // 2 up / 2 down, and the tie sits at positions 2-3 -- entirely above the
    // "top 4 advance" line, so nothing used to say the tie decided a bracket.
    const group = groupItem(101, 4);
    const groups = stage([group]);

    await mount(
      [
        standing(1, group, groups),
        standing(2, group, groups, { tie_group: 2 }),
        standing(3, group, groups, { tie_group: 2 }),
        standing(4, group, groups),
        standing(5, group, groups)
      ],
      [groups, splitPlayoff()]
    );

    const upper = container.querySelector(".st-upper-cut");
    expect(upper?.getAttribute("data-label")).toBe("Top 2 → upper bracket");
    const tied = [...container.querySelectorAll("tbody tr.tie")];
    expect(tied).toHaveLength(2);
    expect(tied[0].querySelector(".st-status")?.getAttribute("title")).toBe(
      en.standings.tieDecidesUpper
    );
  });

  it("stays silent when the playoff does not split the advancing teams", async () => {
    const group = groupItem(101, 4);
    const groups = stage([group]);
    const playoff = { ...splitPlayoff(), split_lower_bracket: false };

    await mount(
      [1, 2, 3, 4, 5].map((position) => standing(position, group, groups)),
      [groups, playoff]
    );

    expect(container.querySelector(".st-upper-cut")).toBeNull();
  });

  it("draws no line for an odd share the seed list splits across groups", async () => {
    // Without a Lower-bracket item the engine halves the CONCATENATED seed list,
    // which for an odd per-group share lands mid-group: this table cannot say
    // where, so it says nothing rather than guessing.
    const group = groupItem(101, 3);
    const groups = stage([group]);

    await mount(
      [1, 2, 3, 4].map((position) => standing(position, group, groups)),
      [groups, splitPlayoff()]
    );

    expect(container.querySelector(".st-upper-cut")).toBeNull();
  });

  it("splits each group's own share once the playoff has a lower-bracket lane", async () => {
    const group = groupItem(101, 3);
    const groups = stage([group]);
    const lowerLane: StageItem = { ...groupItem(200, null), type: "bracket_lower", stage_id: 8 };

    await mount(
      [1, 2, 3, 4].map((position) => standing(position, group, groups)),
      [groups, splitPlayoff([lowerLane])]
    );

    // advance_split sends the odd team up: 2 upper, 1 lower.
    expect(container.querySelector(".st-upper-cut")?.getAttribute("data-label")).toBe(
      "Top 2 → upper bracket"
    );
  });
});
