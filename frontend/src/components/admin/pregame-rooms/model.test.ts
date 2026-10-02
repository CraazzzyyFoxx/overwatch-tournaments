import { describe, expect, it } from "vitest";

import type { PregameKindSummary, PregameRoomRow } from "@/types/admin.types";

import { currentStep, sortRooms } from "./model";

function summary(overrides: Partial<PregameKindSummary> = {}): PregameKindSummary {
  return {
    status: "active",
    reason: null,
    current_round: 1,
    step_index: 2,
    step_count: 6,
    step_action: "ban",
    step_blind: false,
    acting_sides: ["home"],
    step_started_at: "2026-10-02T10:00:00Z",
    deadline_at: "2026-10-02T10:01:00Z",
    awaiting_choice: false,
    ...overrides
  };
}

function room(overrides: Partial<PregameRoomRow> = {}): PregameRoomRow {
  return {
    encounter_id: 1,
    name: "A vs B",
    stage_id: 5,
    stage_name: "Groups",
    round: 1,
    best_of: 3,
    scheduled_at: null,
    status: "PENDING",
    result_status: "none",
    home_team: { id: 1, name: "A" },
    away_team: { id: 2, name: "B" },
    home_score: 0,
    away_score: 0,
    readiness: { home: false, away: false },
    phase: "readiness",
    map: null,
    hero: null,
    games: { total: 0, confirmed: 0, disputed: 0, awaiting_result: 0 },
    attention: [],
    ...overrides
  };
}

describe("sortRooms", () => {
  it("floats anything needing attention, then sorts by kick-off with unscheduled last", () => {
    const order = sortRooms([
      room({ encounter_id: 1, scheduled_at: "2026-10-02T12:00:00Z" }),
      room({ encounter_id: 2, scheduled_at: null }),
      room({ encounter_id: 3, scheduled_at: "2026-10-02T09:00:00Z" }),
      room({ encounter_id: 4, scheduled_at: "2026-10-02T23:00:00Z", attention: ["overdue"] })
    ]).map((entry) => entry.encounter_id);

    expect(order).toEqual([4, 3, 1, 2]);
  });

  it("keeps the server's order for rows the comparator cannot tell apart", () => {
    const order = sortRooms([
      room({ encounter_id: 7 }),
      room({ encounter_id: 5 }),
      room({ encounter_id: 6 })
    ]).map((entry) => entry.encounter_id);

    // Not sorted by id: stage order, round and id are already baked into the
    // sequence the endpoint returned.
    expect(order).toEqual([7, 5, 6]);
  });
});

describe("currentStep", () => {
  it("names the session actually holding the room, not the phase's kind", () => {
    // Map veto done, hero room paused on the loser's choice while the
    // encounter sits in `report` — the column must still say "Heroes".
    const step = currentStep(
      room({
        phase: "report",
        map: summary({ status: "completed", step_index: null, awaiting_choice: false }),
        hero: summary({ step_index: null, awaiting_choice: true })
      })
    );

    expect(step?.kind).toBe("hero");
  });

  it("ignores a session with nothing open", () => {
    expect(currentStep(room({ map: summary({ step_index: null }) }))).toBeNull();
    expect(currentStep(room({ map: summary({ status: null, reason: "not_ready" }) }))).toBeNull();
  });
});
