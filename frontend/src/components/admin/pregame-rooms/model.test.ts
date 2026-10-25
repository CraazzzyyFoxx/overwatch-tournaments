import { createTable, getCoreRowModel, getSortedRowModel } from "@tanstack/react-table";
import { describe, expect, it } from "vitest";

import type { PregameKindSummary, PregameRoomRow } from "@/types/admin.types";

import { currentStep, sortByKickoff } from "./model";

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
    paused_at: null,
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

/** Encounter ids in the order a real TanStack table sorts the "Scheduled" column. */
function kickoffOrder(rooms: PregameRoomRow[], desc: boolean): number[] {
  const table = createTable<PregameRoomRow>({
    data: rooms,
    columns: [{ accessorKey: "scheduled_at", sortingFn: sortByKickoff }],
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    state: {},
    onStateChange: () => {},
    renderFallbackValue: null
  });
  table.setOptions((prev) => ({ ...prev, state: { ...table.initialState, sorting: [{ id: "scheduled_at", desc }] } }));
  return table.getRowModel().rows.map((row) => row.original.encounter_id);
}

describe("sortByKickoff", () => {
  it("puts unscheduled rooms first when newest first, breaks ties by the latest bracket position, and mirrors exactly", () => {
    // Bracket order as the server answers it, reversed the way the browser hands it over.
    const rooms = [
      room({ encounter_id: 1, scheduled_at: "2026-10-02T09:00:00Z" }),
      room({ encounter_id: 2, scheduled_at: "2026-10-02T12:00:00Z" }),
      room({ encounter_id: 3, scheduled_at: null }),
      room({ encounter_id: 4, scheduled_at: "2026-10-02T12:00:00Z" }),
      room({ encounter_id: 5, scheduled_at: null })
    ].reverse();

    expect(kickoffOrder(rooms, true)).toEqual([5, 3, 4, 2, 1]);
    expect(kickoffOrder(rooms, false)).toEqual([1, 2, 4, 3, 5]);
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

  it("falls back to a session an organizer cancelled, so the cell is not blank", () => {
    const step = currentStep(
      room({
        phase: "report",
        map: summary({ status: "cancelled", step_index: null, current_round: null }),
        hero: summary({ status: "completed", step_index: null })
      })
    );

    expect(step?.kind).toBe("map");
    expect(step?.summary.status).toBe("cancelled");
  });
});
