import { describe, expect, it } from "bun:test";

import type { Encounter } from "@/types/encounter.types";
import {
  DEFAULT_FILTERS,
  filtersToApiFilters,
  filtersToSearchParams,
  formatDuration,
  getEncounterStateLabel,
  getMediaSlots,
  normalizeEncounterFilters,
} from "./encounters-redesign.helpers";

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
    tournament_group_id: null,
    stage_id: null,
    stage_item_id: null,
    challonge_id: null,
    challonge_slug: null,
    status: "open",
    closeness: null,
    has_logs: false,
    result_status: "none",
    scheduled_at: null,
    started_at: null,
    ended_at: null,
    current_map_index: null,
    submitted_by_id: null,
    submitted_at: null,
    confirmed_by_id: null,
    confirmed_at: null,
    matches: [],
    home_team: null as never,
    away_team: null as never,
    tournament: null as never,
    stage: null,
    stage_item: null,
    tournament_group: null,
    ...overrides,
  };
}

describe("encounters redesign helpers", () => {
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

    expect(getEncounterStateLabel(encounter({ started_at: "2026-05-18T11:00:00Z" }), now)).toBe("Live");
    expect(getEncounterStateLabel(encounter({ scheduled_at: "2026-05-18T13:00:00Z" }), now)).toBe("Upcoming");
    expect(getEncounterStateLabel(encounter({ status: "completed" }), now)).toBe("Final");
  });

  it("keeps VOD and cast as disabled Twitch placeholders", () => {
    expect(getMediaSlots(true)).toEqual([
      { key: "logs", label: "Game logs available", enabled: true },
      { key: "vod", label: "Coming with Twitch integration", enabled: false },
      { key: "cast", label: "Coming with Twitch integration", enabled: false },
    ]);
  });

  it("formats aggregate seconds for pulse cards", () => {
    expect(formatDuration(2520)).toBe("42m");
    expect(formatDuration(4500)).toBe("1h 15m");
  });
});
