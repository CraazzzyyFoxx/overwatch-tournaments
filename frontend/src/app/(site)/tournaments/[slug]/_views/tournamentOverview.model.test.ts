import { describe, expect, it } from "vitest";

import type { Encounter, EncounterTeam } from "@/types/encounter.types";
import type { StageItem, Standings, Tournament } from "@/types/tournament.types";

import { buildGroupRows } from "./tournamentOverview.model";

const STAGE_ID = 7;

function group(id: number, name: string, advanceCount: number | null): StageItem {
  return {
    id,
    stage_id: STAGE_ID,
    name,
    type: "group",
    order: id,
    advance_count: advanceCount,
    advance_upper_count: null,
    inputs: []
  };
}

/** Group B sorts after Group A by name, though its id comes first. */
const GROUP_A = group(2, "Group A", 2);
const GROUP_B = group(1, "Group B", null);

function standing(teamId: number, item: StageItem, position: number, points: number): Standings {
  return {
    id: teamId,
    tournament_id: 1,
    team_id: teamId,
    stage_id: STAGE_ID,
    stage_item_id: item.id,
    position,
    overall_position: position,
    matches: 0,
    win: 0,
    draw: 0,
    lose: 0,
    points,
    buchholz: null,
    full_buchholz: null,
    tie_group: null,
    is_pinned: false,
    swiss_status: null,
    tb: null,
    score_differential: null,
    ranking_context: null,
    tb_metrics: null,
    source_rule_profile: null,
    tiebreak_order: null,
    team: null,
    tournament: null,
    stage: null,
    stage_item: item,
    matches_history: []
  };
}

function seat(slot: number, teamId: number, score: number): EncounterTeam {
  return {
    id: teamId * 10 + slot,
    slot,
    team_id: teamId,
    name: `Team ${teamId}`,
    seed: null,
    score,
    placement: null,
    active: true,
    team: null
  };
}

/** A series between two teams; `one` holds slot 1. */
function series(
  id: number,
  round: number,
  [one, oneScore]: [number, number],
  [two, twoScore]: [number, number],
  status = "completed"
): Encounter {
  return {
    id,
    created_at: new Date(0),
    updated_at: null,
    workspace_id: 1,
    discipline: "overwatch",
    name: `${one} vs ${two}`,
    slot_count: 2,
    scoring_preset: "wins",
    round,
    best_of: 3,
    tournament_id: 1,
    stage_id: STAGE_ID,
    stage_item_id: GROUP_A.id,
    challonge_id: null,
    status,
    closeness: null,
    has_logs: false,
    result_status: "confirmed",
    result_source: "series_claim",
    result_version: 1,
    scheduled_at: null,
    started_at: null,
    ended_at: null,
    current_map_index: null,
    confirmed_at: null,
    played_at: null,
    is_live: status !== "completed",
    is_final: false,
    matches: [],
    games: [],
    teams: [seat(1, one, oneScore), seat(2, two, twoScore)],
    // Not read by the group tables.
    tournament: {} as Tournament
  };
}

/**
 * Group A by the official standings: 2, 1, 3 — though team 1 has the better finished results, a tiebreaker or an
 * organizer's pin put team 2 on top. Rows arrive shuffled. Group B's lone team has played nothing yet.
 */
const STANDINGS = [
  standing(3, GROUP_A, 3, 1),
  standing(4, GROUP_B, 1, 0),
  standing(1, GROUP_A, 2, 3),
  standing(2, GROUP_A, 1, 4)
];

/** Listed newest round first, so a form kept in list order would read backwards. */
const ENCOUNTERS = [
  series(30, 3, [2, 1], [3, 1]),
  series(20, 2, [1, 2], [2, 0]),
  series(10, 1, [3, 2], [1, 1]),
  // Still being played: neither its 2–0 nor its result count yet.
  series(40, 4, [1, 2], [3, 0], "live")
];

describe("buildGroupRows", () => {
  const rows = buildGroupRows({ advance_count: 3 }, STANDINGS, ENCOUNTERS);

  it("orders, places and scores each group by the official standings", () => {
    expect(rows.map(({ teamId, position, points }) => ({ teamId, position, points }))).toEqual([
      { teamId: 2, position: 1, points: 4 },
      { teamId: 1, position: 2, points: 3 },
      { teamId: 3, position: 3, points: 1 },
      { teamId: 4, position: 1, points: 0 }
    ]);
  });

  it("splits the rows by stage item, the group overriding the stage's advance count", () => {
    expect(
      rows.map(({ groupKey, groupName, advance }) => ({ groupKey, groupName, advance }))
    ).toEqual([
      { groupKey: "2", groupName: "Group A", advance: 2 },
      { groupKey: "2", groupName: "Group A", advance: 2 },
      { groupKey: "2", groupName: "Group A", advance: 2 },
      { groupKey: "1", groupName: "Group B", advance: 3 }
    ]);
  });

  it("reads form oldest round first and map difference from finished series only", () => {
    expect(rows.map(({ teamId, form, mapDiff }) => ({ teamId, form, mapDiff }))).toEqual([
      { teamId: 2, form: ["l", "d"], mapDiff: -2 },
      { teamId: 1, form: ["l", "w"], mapDiff: 1 },
      { teamId: 3, form: ["w", "d"], mapDiff: 1 },
      { teamId: 4, form: [], mapDiff: 0 }
    ]);
  });
});
