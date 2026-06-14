import { describe, expect, it } from "bun:test";

import type { Encounter } from "@/types/encounter.types";
import { sortStandingsMatches } from "@/lib/tournament-match-order";

function createEncounter(id: number, round: number): Encounter {
  return {
    id,
    created_at: new Date(0),
    updated_at: null,
    name: `Match ${id}`,
    home_team_id: 1,
    away_team_id: 2,
    score: { home: 0, away: 0 },
    round,
    best_of: 3,
    tournament_id: 1,
    tournament_group_id: null,
    stage_id: 1,
    stage_item_id: 1,
    challonge_id: null,
    challonge_slug: null,
    status: "completed",
    closeness: null,
    has_logs: false,
    result_status: "confirmed",
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
  };
}

describe("sortStandingsMatches", () => {
  it("sorts round-robin history by round number instead of encounter id", () => {
    const sorted = sortStandingsMatches([
      createEncounter(30, 3),
      createEncounter(10, 1),
      createEncounter(20, 2),
    ]);

    expect(sorted.map((encounter) => encounter.round)).toEqual([1, 2, 3]);
    expect(sorted.map((encounter) => encounter.id)).toEqual([10, 20, 30]);
  });

  it("keeps double-elimination ordering aligned with bracket rounds", () => {
    const sorted = sortStandingsMatches([
      createEncounter(50, 3),
      createEncounter(10, 1),
      createEncounter(40, -2),
      createEncounter(20, -1),
      createEncounter(30, 2),
    ]);

    expect(sorted.map((encounter) => encounter.round)).toEqual([1, -1, 2, -2, 3]);
  });

  it("sorts playoff final rounds in the correct chronological order", () => {
    const sorted = sortStandingsMatches([
      createEncounter(60, 6),   // Grand Final
      createEncounter(50, 5),   // UB Final
      createEncounter(55, -8),  // LB Final
      createEncounter(70, 7),   // Grand Final Reset
    ]);
    expect(sorted.map((encounter) => encounter.round)).toEqual([5, -8, 6, 7]);
  });
});
