import { describe, expect, it } from "vitest";

import type { EncounterMapPoolEntry, EncounterMapPoolState } from "@/types/tournament.types";

import { buildMapCodeSlots } from "./matchReportSlots";

function entry(overrides: Partial<EncounterMapPoolEntry>): EncounterMapPoolEntry {
  return {
    id: 1,
    map_id: 100,
    order: 1,
    action_index: null,
    picked_by: null,
    team_id: null,
    status: "available",
    ...overrides,
  };
}

function poolState(pool: EncounterMapPoolEntry[]): EncounterMapPoolState {
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
    is_complete: false,
  };
}

describe("buildMapCodeSlots", () => {
  it("builds ordered named slots from picked pool entries", () => {
    const state = poolState([
      entry({ id: 1, map_id: 10, order: 3, status: "picked" }),
      entry({ id: 2, map_id: 20, order: 1, status: "picked" }),
      entry({ id: 3, map_id: 30, order: 5, status: "banned" }),
      entry({ id: 4, map_id: 40, order: 2, status: "picked" }),
    ]);

    expect(buildMapCodeSlots(state, 5)).toEqual([
      { mapIndex: 1, mapId: 20 },
      { mapIndex: 2, mapId: 40 },
      { mapIndex: 3, mapId: 10 },
    ]);
  });

  it("falls back to best_of unnamed slots when there is no picked pool", () => {
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
