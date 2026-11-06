// The bracket projection, which has never had a test: it lived inside 2450
// lines of `StageManager` JSX, and every claim below was previously only
// checkable by clicking through a tournament.
//
// What it has to get right is that the admin sees the bracket the BACKEND will
// generate: the depth follows the seeds and slots actually seated in the stage.
// Getting that wrong offers the organizer best-of rows for rounds that will
// never exist (or hides rows for rounds that will).
import { describe, expect, test } from "vitest";

import type { Stage, StageItem, StageItemType, StageType } from "@/types/tournament.types";

import {
  getStageStatus,
  projectStage,
  projectedRoundRobinRounds,
  resolveBracketTeamCount
} from "@/lib/bracket/projection";

function item(
  id: number,
  type: StageItemType,
  { seeded = 0, empty = 0 }: { seeded?: number; empty?: number } = {}
): StageItem {
  const inputs = [
    ...Array.from({ length: seeded }, (_, index) => ({
      id: id * 100 + index,
      stage_item_id: id,
      slot: index + 1,
      input_type: "final" as const,
      team_id: index + 1,
      source_result_id: null
    })),
    ...Array.from({ length: empty }, (_, index) => ({
      id: id * 100 + seeded + index,
      stage_item_id: id,
      slot: seeded + index + 1,
      input_type: "empty" as const,
      team_id: null,
      source_result_id: null
    }))
  ];
  return {
    id,
    stage_id: 1,
    name: `Item ${id}`,
    type,
    order: 0,
    inputs
  };
}

function stage(overrides: Partial<Stage> & { id: number; stage_type: StageType }): Stage {
  return {
    tournament_id: 1,
    name: `Stage ${overrides.id}`,
    description: null,
    max_rounds: 5,
    order: overrides.id,
    node_id: 1,
    status: "draft",
    is_published: false,
    ranking_preset: null,
    tiebreak_order: null,
    scoring: { win: null, draw: null, loss: null },
    swiss_bye_points: null,
    swiss_qualify_wins: null,
    swiss_eliminate_losses: null,
    de_grand_final_type: "no_reset",
    seed_ranking: "slot",
    best_of: { default: 3, by_round: {}, final: null, swiss_qualify: null, swiss_eliminate: null },
    ffa_scoring: { placement_points: [], score_points: 1, score_label: null },
    challonge_id: null,
    challonge_slug: null,
    items: [],
    ...overrides
  };
}


// A round robin's length is its team count, not `max_rounds`: everyone plays
// everyone, so an even field of `n` needs `n - 1` rounds and an odd one pads
// with a BYE (`services/bracket/round_robin.py`).
describe("projectedRoundRobinRounds", () => {
  test("an even group plays one round fewer than it has teams", () => {
    const groups = stage({ id: 1, stage_type: "round_robin", items: [item(10, "group", { seeded: 6 })] });

    expect(projectedRoundRobinRounds(groups)).toBe(5);
  });

  test("an odd group pads with a BYE, so it plays as many rounds as it has teams", () => {
    const groups = stage({ id: 1, stage_type: "round_robin", items: [item(10, "group", { seeded: 5 })] });

    expect(projectedRoundRobinRounds(groups)).toBe(5);
  });

  test("the stage is as long as its largest group, and counts empty slots", () => {
    const groups = stage({
      id: 1,
      stage_type: "round_robin",
      items: [item(10, "group", { seeded: 4 }), item(11, "group", { empty: 8 })]
    });

    expect(projectedRoundRobinRounds(groups)).toBe(7);
  });

  test("nothing wired in derives nothing — the caller falls back to max_rounds", () => {
    expect(projectedRoundRobinRounds(stage({ id: 1, stage_type: "round_robin" }))).toBe(0);
    expect(
      projectedRoundRobinRounds(
        stage({ id: 1, stage_type: "round_robin", items: [item(10, "group", { seeded: 1 })] })
      )
    ).toBe(0);
  });
});

describe("resolveBracketTeamCount", () => {
  test("seeded teams are ground truth, ahead of the empty slots beside them", () => {
    const playoff = stage({
      id: 2,
      stage_type: "single_elimination",
      items: [item(20, "single_bracket", { seeded: 6, empty: 10 })]
    });

    expect(resolveBracketTeamCount(playoff)).toEqual({
      count: 6,
      source: "seeded"
    });
  });

  test("falls back to the wired slots when nothing is seeded yet", () => {
    const playoff = stage({
      id: 2,
      stage_type: "single_elimination",
      items: [item(20, "single_bracket", { empty: 8 })]
    });

    expect(resolveBracketTeamCount(playoff)).toEqual({
      count: 8,
      source: "slots"
    });
  });

  test("a DE with a lower-bracket lane counts the upper bracket only", () => {
    const playoff = stage({
      id: 2,
      stage_type: "double_elimination",
      items: [item(20, "bracket_upper", { seeded: 4 }), item(21, "bracket_lower", { seeded: 8 })]
    });

    // The lower-bracket item does not deepen the upper bracket.
    expect(resolveBracketTeamCount(playoff)).toEqual({
      count: 4,
      source: "seeded"
    });
  });

  test("one bracket item is the whole upper bracket — nothing is halved", () => {
    // Lower-bracket seeds live in a `bracket_lower` item or nowhere; a single
    // item used to be cut down the middle, which shortened the bracket by one.
    const playoff = stage({
      id: 2,
      stage_type: "double_elimination",
      items: [item(20, "single_bracket", { seeded: 8 })]
    });

    expect(resolveBracketTeamCount(playoff).count).toBe(8);
  });

  test("reports `unknown` rather than 0 teams when there is nothing to read", () => {
    const playoff = stage({ id: 2, stage_type: "single_elimination" });

    expect(resolveBracketTeamCount(playoff)).toEqual({
      count: 0,
      source: "unknown"
    });
  });
});

describe("projectStage", () => {
  const playoff = stage({
    id: 2,
    stage_type: "double_elimination",
    max_rounds: 5,
    items: [item(20, "single_bracket", { seeded: 8 })]
  });

  test("an 8-team double elimination projects UB 1..3, LB -1..-4 and a grand final", () => {
    const projection = projectStage({
      stage: playoff,
      stageType: "double_elimination",
      maxRounds: 5,
      bestOf: { default: 3, by_round: {}, final: null, swiss_qualify: null, swiss_eliminate: null }
    });

    expect(projection.rounds.map((round) => [round.section, round.label, round.round])).toEqual([
      ["Upper bracket", "UB Round 1", 1],
      ["Upper bracket", "UB Semifinal", 2],
      ["Upper bracket", "UB Final", 3],
      ["Lower bracket", "LB Round 1", -1],
      ["Lower bracket", "LB Round 2", -2],
      ["Lower bracket", "LB Round 3", -3],
      ["Lower bracket", "LB Final", -4],
      [null, "Grand Final", 4]
    ]);
  });

  test("follows the engine's planned rounds over the team-count formula", () => {
    // 4 upper / 8 lower: the engine's rounds say UB 1..2, LB -1..-5, GF 3.
    const projection = projectStage({
      stage: playoff,
      stageType: "double_elimination",
      maxRounds: 5,
      bestOf: { default: 3, by_round: {}, final: null, swiss_qualify: null, swiss_eliminate: null },
      plannedRounds: [-5, -4, -3, -2, -1, 1, 2, 3]
    });

    expect(projection.rounds.map((round) => round.round)).toEqual([
      1, 2, -1, -2, -3, -4, -5, 3
    ]);
    expect(projection.rounds.filter((round) => round.isFinal).map((round) => round.round)).toEqual([
      3
    ]);
  });

  test("resolves each round's series length the way the backend does", () => {
    const projection = projectStage({
      stage: playoff,
      stageType: "double_elimination",
      maxRounds: 5,
      // `final` targets the grand final and outranks a `by_round` key on it.
      bestOf: { default: 3, by_round: { "1": 1, "4": 3 }, final: 7, swiss_qualify: null, swiss_eliminate: null }
    });
    const bestOfByLabel = Object.fromEntries(
      projection.rounds.map((round) => [round.label, round.bestOf])
    );

    expect(bestOfByLabel).toMatchObject({
      "UB Round 1": 1,
      "UB Semifinal": 3,
      "LB Final": 3,
      "Grand Final": 7
    });
    // Only the grand final carries the final flag in double elimination — the
    // last upper-bracket round is not the stage's final.
    expect(projection.rounds.filter((round) => round.isFinal).map((round) => round.label)).toEqual([
      "Grand Final"
    ]);
  });

  test("single elimination has one flat list whose last round IS the final", () => {
    const bracket = stage({
      id: 2,
      stage_type: "single_elimination",
      items: [item(20, "single_bracket", { seeded: 8 })]
    });

    const projection = projectStage({
      stage: bracket,
      stageType: "single_elimination",
      maxRounds: 5,
      bestOf: { default: 3, by_round: {}, final: 5, swiss_qualify: null, swiss_eliminate: null }
    });

    expect(projection.rounds.map((round) => round.label)).toEqual([
      "Round 1",
      "Round 2",
      "Round 3"
    ]);
    expect(projection.rounds.at(-1)).toMatchObject({ isFinal: true, bestOf: 5 });
  });

  test("counts the unresolved slots of a group stage", () => {
    const groups = stage({
      id: 1,
      stage_type: "round_robin",
      items: [item(10, "group", { seeded: 3, empty: 1 }), item(11, "group", { seeded: 4 })]
    });

    const projection = projectStage({
      stage: groups,
      stageType: "round_robin",
      maxRounds: 3,
      bestOf: { default: 3, by_round: {}, final: null, swiss_qualify: null, swiss_eliminate: null }
    });

    expect(projection).toMatchObject({
      isGroups: true,
      isBracket: false,
      itemCount: 2,
      slots: 8,
      assigned: 7,
      unresolved: 1
    });
  });
});

describe("getStageStatus", () => {
  test("a generated but unpublished stage reads Preview, not Draft", () => {
    const s = stage({ id: 1, stage_type: "swiss" });
    expect(getStageStatus(s, false)).toBe("Draft");
    expect(getStageStatus(s, true)).toBe("Preview");
    expect(getStageStatus({ ...s, status: "live" }, true)).toBe("Active");
    expect(getStageStatus({ ...s, status: "completed" }, true)).toBe("Completed");
  });
});
