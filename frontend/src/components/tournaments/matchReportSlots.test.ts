import { describe, expect, it } from "vitest";

import type { PickBanEntry, PickBanState } from "@/types/tournament.types";

import { buildMapCodeSlots } from "./matchReportSlots";

function entry(overrides: Partial<PickBanEntry>): PickBanEntry {
  return {
    id: 1,
    item_id: 100,
    round: null,
    order: 1,
    action_index: null,
    picked_by: null,
    protected_by: null,
    status: "available",
    team_id: null,
    ...overrides,
  };
}

function poolState(pool: PickBanEntry[]): PickBanState {
  return {
    session: null,
    sequence: [],
    pool,
    viewer_side: null,
    viewer_can_act: false,
    allowed_actions: [],
    current_step_index: null,
    current_step: null,
    expected_action: null,
    turn_side: null,
    current_round: null,
    is_complete: false,
  };
}

describe("buildMapCodeSlots", () => {
  it("indexes the settled maps 1..n in play order", () => {
    // `order` is a per-round display field: it starts at 0 and later rounds are
    // spaced by `round * 1000`, so reading the index off it sent `map_index: 0`
    // (rejected by the server) and `1000` for the second map. `action_index` is
    // the veto's global action order, which IS the play order.
    const state = poolState([
      entry({ id: 1, item_id: 10, order: 2000, action_index: 7, status: "picked" }),
      entry({ id: 2, item_id: 20, order: 0, action_index: 3, status: "picked" }),
      entry({ id: 3, item_id: 30, order: 1, action_index: 2, status: "banned" }),
      entry({ id: 4, item_id: 40, order: 1000, action_index: 5, status: "picked" }),
    ]);

    expect(buildMapCodeSlots(state, 3)).toEqual([
      { mapIndex: 1, mapId: 20 },
      { mapIndex: 2, mapId: 40 },
      { mapIndex: 3, mapId: 10 },
    ]);
  });

  it("orders by the pool order when no action index was recorded", () => {
    const state = poolState([
      entry({ id: 1, item_id: 10, order: 5, status: "picked" }),
      entry({ id: 2, item_id: 20, order: 2, status: "picked" }),
    ]);

    expect(buildMapCodeSlots(state, 3)).toEqual([
      { mapIndex: 1, mapId: 20 },
      { mapIndex: 2, mapId: 10 },
    ]);
  });

  it("falls back to best_of unnamed slots when nothing is settled", () => {
    expect(buildMapCodeSlots(null, 5)).toEqual([
      { mapIndex: 1, mapId: null },
      { mapIndex: 2, mapId: null },
      { mapIndex: 3, mapId: null },
      { mapIndex: 4, mapId: null },
      { mapIndex: 5, mapId: null },
    ]);

    expect(buildMapCodeSlots(poolState([entry({ status: "available" })]), null)).toEqual([
      { mapIndex: 1, mapId: null },
      { mapIndex: 2, mapId: null },
      { mapIndex: 3, mapId: null },
    ]);
  });
});
