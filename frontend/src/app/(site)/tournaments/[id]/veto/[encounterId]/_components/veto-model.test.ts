import { describe, expect, it } from "vitest";

import type {
  EncounterMapPoolEntry,
  EncounterMapPoolState,
  EncounterVetoSession,
} from "@/types/tournament.types";

import { parseStepToken, pickedMapsInOrder, turnDeadlineMs } from "./veto-model";

function entry(overrides: Partial<EncounterMapPoolEntry>): EncounterMapPoolEntry {
  return {
    id: 1,
    map_id: 1,
    order: 0,
    action_index: null,
    picked_by: null,
    status: "available",
    ...overrides,
  };
}

function session(overrides: Partial<EncounterVetoSession>): EncounterVetoSession {
  return {
    id: 1,
    status: "active",
    first_side: "home",
    seed_source: "bracket_slot",
    home_seed: 1,
    away_seed: 2,
    turn_timer_seconds: 60,
    started_at: "2026-07-18T10:00:00Z",
    current_step_started_at: "2026-07-18T10:00:00Z",
    ...overrides,
  };
}

function state(overrides: Partial<EncounterMapPoolState>): EncounterMapPoolState {
  return {
    session: session({}),
    sequence: [],
    pool: [],
    viewer_side: null,
    viewer_can_act: false,
    allowed_actions: [],
    current_step_index: 0,
    current_step: null,
    expected_action: null,
    turn_side: null,
    is_complete: false,
    ...overrides,
  };
}

describe("parseStepToken", () => {
  it("splits side-resolved tokens into action + side", () => {
    expect(parseStepToken("ban_home")).toEqual({ token: "ban_home", action: "ban", side: "home" });
    expect(parseStepToken("pick_away")).toEqual({
      token: "pick_away",
      action: "pick",
      side: "away",
    });
  });

  it("treats decider as sideless", () => {
    expect(parseStepToken("decider")).toEqual({ token: "decider", action: "decider", side: null });
  });
});

describe("pickedMapsInOrder", () => {
  it("keeps picked and played maps sorted by global action order", () => {
    const pool = [
      entry({ id: 1, map_id: 11, status: "banned", action_index: 0 }),
      entry({ id: 2, map_id: 12, status: "played", action_index: 3 }),
      entry({ id: 3, map_id: 13, status: "picked", action_index: 2 }),
      entry({ id: 4, map_id: 14, status: "available" }),
    ];
    expect(pickedMapsInOrder(pool).map((e) => e.map_id)).toEqual([13, 12]);
  });

  it("falls back to legacy `order` when action_index is missing", () => {
    const pool = [
      entry({ id: 1, map_id: 11, status: "picked", order: 2 }),
      entry({ id: 2, map_id: 12, status: "picked", order: 1 }),
    ];
    expect(pickedMapsInOrder(pool).map((e) => e.map_id)).toEqual([12, 11]);
  });
});

describe("turnDeadlineMs", () => {
  it("computes started_at + timer for an active session", () => {
    const deadline = turnDeadlineMs(state({}));
    expect(deadline).toBe(Date.parse("2026-07-18T10:00:00Z") + 60_000);
  });

  it("hides the indicator when no timer is configured", () => {
    expect(turnDeadlineMs(state({ session: session({ turn_timer_seconds: null }) }))).toBeNull();
    expect(
      turnDeadlineMs(state({ session: session({ current_step_started_at: null }) })),
    ).toBeNull();
  });

  it("hides the indicator for inactive or finished sessions", () => {
    expect(turnDeadlineMs(state({ session: session({ status: "completed" }) }))).toBeNull();
    expect(turnDeadlineMs(state({ is_complete: true }))).toBeNull();
    expect(turnDeadlineMs(state({ session: null }))).toBeNull();
  });
});
