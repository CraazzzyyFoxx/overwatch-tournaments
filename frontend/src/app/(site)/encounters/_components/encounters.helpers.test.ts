import { describe, expect, it } from "vitest";

import type { Encounter } from "@/types/encounter.types";
import { getEncounterState, getEncounterWinner } from "@/lib/encounter/status";
import {
  DEFAULT_FILTERS,
  filtersToApiFilters,
  filtersToSearchParams,
  formatDuration,
  normalizeEncounterFilters,
} from "./encounters.helpers";

function encounter(overrides: Partial<Encounter>): Encounter {
  return {
    id: 1,
    created_at: new Date("2026-05-01T12:00:00Z"),
    updated_at: null,
    name: "A vs B",
    home_team_id: 1,
    away_team_id: 2,
    score: { home: 0, away: 0 },
    round: 1,
    best_of: 3,
    tournament_id: 1,
    stage_id: null,
    stage_item_id: null,
    challonge_id: null,
    status: "open",
    closeness: null,
    has_logs: false,
    result_status: "none",
    scheduled_at: null,
    started_at: null,
    ended_at: null,
    current_map_index: null,
    confirmed_at: null,
    matches: [],
    home_team: null as never,
    away_team: null as never,
    tournament: null as never,
    stage: null,
    stage_item: null,
    ...overrides,
  };
}

describe("encounters helpers", () => {
  it("normalizes URL filters with stable defaults", () => {
    expect(
      normalizeEncounterFilters({
        search: "final",
        best_of: "5",
        has_logs: "true",
        scope: "my_team",
        sort: "closeness",
      }),
    ).toEqual({
      ...DEFAULT_FILTERS,
      query: "final",
      best_of: 5,
      has_logs: true,
      scope: "my_team",
      sort: "closeness",
    });
  });

  it("serializes only non-default query parameters", () => {
    const params = filtersToSearchParams(
      {
        ...DEFAULT_FILTERS,
        query: "wis",
        best_of: 5,
        has_logs: true,
      },
      3,
    );

    expect(params.toString()).toBe("search=wis&page=3&best_of=5&has_logs=true");
  });

  it("maps UI sort keys to backend sort columns", () => {
    expect(filtersToApiFilters({ ...DEFAULT_FILTERS, sort: "date" }).sort).toBe("id");
    expect(filtersToApiFilters({ ...DEFAULT_FILTERS, sort: "closeness" }).sort).toBe("closeness");
    expect(filtersToApiFilters({ ...DEFAULT_FILTERS, sort: "upcoming" }).sort).toBe("scheduled_at");
  });

  it("labels live, upcoming, and final encounters", () => {
    const now = new Date("2026-05-18T12:00:00Z");

    expect(getEncounterState(encounter({ started_at: "2026-05-18T11:00:00Z" }), now)).toBe("Live");
    expect(getEncounterState(encounter({ scheduled_at: "2026-05-18T13:00:00Z" }), now)).toBe(
      "Upcoming"
    );
    expect(getEncounterState(encounter({ status: "completed" }), now)).toBe("Final");
  });

  it("resolves a winner only once the series is completed", () => {
    expect(getEncounterWinner(encounter({ score: { home: 2, away: 1 } }))).toBeNull();
    expect(
      getEncounterWinner(encounter({ status: "completed", score: { home: 2, away: 1 } }))
    ).toBe("home");
    expect(
      getEncounterWinner(encounter({ status: "completed", score: { home: 1, away: 2 } }))
    ).toBe("away");
    expect(
      getEncounterWinner(encounter({ status: "completed", score: { home: 2, away: 2 } }))
    ).toBeNull();
  });

  it("formats aggregate seconds for pulse cards", () => {
    expect(formatDuration(2520)).toBe("42m");
    expect(formatDuration(4500)).toBe("1h 15m");
  });
});
