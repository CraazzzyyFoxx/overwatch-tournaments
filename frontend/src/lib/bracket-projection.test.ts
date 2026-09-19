// The bracket projection, which has never had a test: it lived inside 2450
// lines of `StageManager` JSX, and every claim below was previously only
// checkable by clicking through a tournament.
//
// What it has to get right is that the admin sees the bracket the BACKEND will
// generate. Two independent sources feed the depth — the seeds/slots actually
// wired into the stage, and, before any exist, the preceding group stage's
// `advance_count × groups` — and a split double elimination splits each
// group's share rather than halving the total. Getting that wrong offers the
// organizer best-of rows for rounds that will never exist (or hides rows for
// rounds that will).
import { describe, expect, test } from "vitest";

import type { Stage, StageItem, StageItemType, StageType } from "@/types/tournament.types";

import {
  buildBestOfSettings,
  getStageStatus,
  projectStage,
  projectedBracketSeedCounts,
  projectedRoundRobinRounds,
  resolveBracketTeamCount
} from "@/lib/bracket-projection";

function item(
  id: number,
  type: StageItemType,
  {
    seeded = 0,
    empty = 0,
    advance = null
  }: { seeded?: number; empty?: number; advance?: number | null } = {}
): StageItem {
  const inputs = [
    ...Array.from({ length: seeded }, (_, index) => ({
      id: id * 100 + index,
      stage_item_id: id,
      slot: index + 1,
      input_type: "final" as const,
      team_id: index + 1,
      source_stage_item_id: null,
      source_position: null
    })),
    ...Array.from({ length: empty }, (_, index) => ({
      id: id * 100 + seeded + index,
      stage_item_id: id,
      slot: seeded + index + 1,
      input_type: "empty" as const,
      team_id: null,
      source_stage_item_id: null,
      source_position: null
    }))
  ];
  return { id, stage_id: 1, name: `Item ${id}`, type, order: 0, advance_count: advance, inputs };
}

function stage(overrides: Partial<Stage> & { id: number; stage_type: StageType }): Stage {
  return {
    tournament_id: 1,
    name: `Stage ${overrides.id}`,
    description: null,
    max_rounds: 5,
    advance_count: null,
    split_lower_bracket: false,
    order: overrides.id,
    is_active: false,
    is_published: false,
    is_completed: false,
    settings_json: null,
    challonge_id: null,
    challonge_slug: null,
    items: [],
    ...overrides
  };
}

describe("projectedBracketSeedCounts", () => {
  test("reads the nearest earlier group stage: advance_count from EACH group", () => {
    const groups = stage({
      id: 1,
      stage_type: "round_robin",
      advance_count: 2,
      items: [item(10, "group"), item(11, "group"), item(12, "group"), item(13, "group")]
    });
    const playoff = stage({ id: 2, stage_type: "single_elimination" });

    // 4 groups × top 2 = 8, not 2.
    expect(projectedBracketSeedCounts(playoff, false, [groups, playoff])).toEqual({
      upper: 8,
      lower: 0
    });
  });

  test("ignores a group stage that comes after, and one with no advance_count", () => {
    const later = stage({ id: 5, stage_type: "swiss", advance_count: 4, items: [item(50, "group")] });
    const unset = stage({ id: 1, stage_type: "swiss", advance_count: null, items: [item(10, "group")] });
    const playoff = stage({ id: 2, stage_type: "single_elimination" });

    expect(projectedBracketSeedCounts(playoff, false, [unset, playoff, later])).toEqual({
      upper: 0,
      lower: 0
    });
  });

  test("projects nothing from a phase running two divisions, as the server refuses to", () => {
    // Low and High share phase 1: neither is "the" preceding stage, so the
    // preview may not pick one — guessing here showed a bracket size that the
    // wiring would never produce.
    const low = stage({ id: 1, order: 1, stage_type: "round_robin", advance_count: 4, items: [item(10, "group")] });
    const high = stage({ id: 2, order: 1, stage_type: "round_robin", advance_count: 4, items: [item(20, "group")] });
    const playoff = stage({ id: 3, order: 2, stage_type: "single_elimination" });

    expect(projectedBracketSeedCounts(playoff, false, [low, high, playoff])).toEqual({
      upper: 0,
      lower: 0
    });
  });

  test("a sibling bracket in the same phase is not a source either", () => {
    const groups = stage({ id: 1, order: 1, stage_type: "swiss", advance_count: 2, items: [item(10, "group")] });
    const sibling = stage({ id: 2, order: 2, stage_type: "single_elimination" });
    const playoff = stage({ id: 3, order: 2, stage_type: "single_elimination" });

    expect(projectedBracketSeedCounts(playoff, false, [groups, sibling, playoff])).toEqual({
      upper: 2,
      lower: 0
    });
  });

  test("splits EACH group's share for a split DE with a dedicated lower item", () => {
    const groups = stage({
      id: 1,
      stage_type: "swiss",
      advance_count: 3,
      items: [item(10, "group"), item(11, "group")]
    });
    const playoff = stage({
      id: 2,
      stage_type: "double_elimination",
      split_lower_bracket: true,
      items: [item(20, "bracket_upper"), item(21, "bracket_lower")]
    });

    // Per group: floor(3/2)=1 down, 2 up. Two groups -> 4 upper, 2 lower.
    // Halving the total (6) would have said 3/3, a differently shaped bracket.
    expect(projectedBracketSeedCounts(playoff, true, [groups, playoff])).toEqual({
      upper: 4,
      lower: 2
    });
  });

  test("splits the seed list down the middle when one item holds both halves", () => {
    const groups = stage({
      id: 1,
      stage_type: "swiss",
      advance_count: 3,
      items: [item(10, "group"), item(11, "group")]
    });
    const playoff = stage({
      id: 2,
      stage_type: "double_elimination",
      split_lower_bracket: true,
      items: [item(20, "single_bracket")]
    });

    expect(projectedBracketSeedCounts(playoff, true, [groups, playoff])).toEqual({
      upper: 3,
      lower: 3
    });
  });

  test("a group's own advance_count overrides the stage's for that group only", () => {
    const groups = stage({
      id: 1,
      stage_type: "round_robin",
      advance_count: 2,
      items: [item(10, "group", { advance: 3 }), item(11, "group")]
    });
    const playoff = stage({ id: 2, stage_type: "single_elimination" });

    // 3 from the group that says so, 2 from the one that inherits — not 2 × 2.
    expect(projectedBracketSeedCounts(playoff, false, [groups, playoff])).toEqual({
      upper: 5,
      lower: 0
    });
  });

  test("a stage with no advance_count still projects the groups that set one", () => {
    const groups = stage({
      id: 1,
      stage_type: "swiss",
      advance_count: null,
      items: [item(10, "group", { advance: 2 })]
    });
    const playoff = stage({ id: 2, stage_type: "single_elimination" });

    expect(projectedBracketSeedCounts(playoff, false, [groups, playoff])).toEqual({
      upper: 2,
      lower: 0
    });
  });

  test("splits an overriding group's share on its own count, not the stage's", () => {
    const groups = stage({
      id: 1,
      stage_type: "swiss",
      advance_count: 2,
      items: [item(10, "group", { advance: 4 }), item(11, "group")]
    });
    const playoff = stage({
      id: 2,
      stage_type: "double_elimination",
      split_lower_bracket: true,
      items: [item(20, "bracket_upper"), item(21, "bracket_lower")]
    });

    // Group A: 4 -> 2 up, 2 down. Group B inherits 2 -> 1 up, 1 down.
    expect(projectedBracketSeedCounts(playoff, true, [groups, playoff])).toEqual({
      upper: 3,
      lower: 3
    });
  });
});

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

    expect(resolveBracketTeamCount(playoff, false, [playoff])).toEqual({
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

    expect(resolveBracketTeamCount(playoff, false, [playoff])).toEqual({
      count: 8,
      source: "slots"
    });
  });

  test("a split DE counts the upper bracket only", () => {
    const playoff = stage({
      id: 2,
      stage_type: "double_elimination",
      split_lower_bracket: true,
      items: [item(20, "bracket_upper", { seeded: 4 }), item(21, "bracket_lower", { seeded: 4 })]
    });

    // The lower-bracket item does not deepen the upper bracket.
    expect(resolveBracketTeamCount(playoff, true, [playoff])).toEqual({
      count: 4,
      source: "seeded"
    });
  });

  test("a split DE in one item takes the first half of its seeds", () => {
    const playoff = stage({
      id: 2,
      stage_type: "double_elimination",
      split_lower_bracket: true,
      items: [item(20, "single_bracket", { seeded: 8 })]
    });

    expect(resolveBracketTeamCount(playoff, true, [playoff]).count).toBe(4);
  });

  test("projects from the group stage when the playoff is not wired at all", () => {
    const groups = stage({
      id: 1,
      stage_type: "swiss",
      advance_count: 2,
      items: [item(10, "group"), item(11, "group")]
    });
    const playoff = stage({ id: 2, stage_type: "single_elimination" });

    expect(resolveBracketTeamCount(playoff, false, [groups, playoff])).toEqual({
      count: 4,
      source: "projected"
    });
  });

  test("reports `unknown` rather than 0 teams when there is nothing to read", () => {
    const playoff = stage({ id: 2, stage_type: "single_elimination" });

    expect(resolveBracketTeamCount(playoff, false, [playoff])).toEqual({
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
      stages: [playoff],
      stageType: "double_elimination",
      splitLowerBracket: false,
      maxRounds: 5,
      bestOf: {}
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

  test("resolves each round's series length the way the backend does", () => {
    const projection = projectStage({
      stage: playoff,
      stages: [playoff],
      stageType: "double_elimination",
      splitLowerBracket: false,
      maxRounds: 5,
      // `final` targets the grand final and outranks a `by_round` key on it.
      bestOf: { default: 3, by_round: { "1": 1, "4": 3 }, final: 7 }
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
      stages: [bracket],
      stageType: "single_elimination",
      splitLowerBracket: false,
      maxRounds: 5,
      bestOf: { default: 3, final: 5 }
    });

    expect(projection.rounds.map((round) => round.label)).toEqual([
      "Round 1",
      "Round 2",
      "Round 3"
    ]);
    expect(projection.rounds.at(-1)).toMatchObject({ isFinal: true, bestOf: 5 });
  });

  test("counts the unresolved slots and what a group stage sends onward", () => {
    const groups = stage({
      id: 1,
      stage_type: "round_robin",
      advance_count: 2,
      items: [item(10, "group", { seeded: 3, empty: 1 }), item(11, "group", { seeded: 4 })]
    });

    const projection = projectStage({
      stage: groups,
      stages: [groups],
      stageType: "round_robin",
      splitLowerBracket: false,
      maxRounds: 3,
      bestOf: {}
    });

    expect(projection).toMatchObject({
      isGroups: true,
      isBracket: false,
      itemCount: 2,
      slots: 8,
      assigned: 7,
      unresolved: 1,
      advancingTotal: 4
    });
  });

  test("what a group stage sends onward adds up each group's own number", () => {
    const groups = stage({
      id: 1,
      stage_type: "round_robin",
      advance_count: 2,
      items: [item(10, "group", { advance: 3 }), item(11, "group")]
    });

    const projection = projectStage({
      stage: groups,
      stages: [groups],
      stageType: "round_robin",
      splitLowerBracket: false,
      maxRounds: 3,
      bestOf: {}
    });

    expect(projection.advancingTotal).toBe(5);
  });
});

describe("buildBestOfSettings", () => {
  test("drops empty fields so an untouched stage sends no `best_of` at all", () => {
    expect(buildBestOfSettings({})).toBeUndefined();
    expect(buildBestOfSettings({ by_round: {} })).toBeUndefined();
  });

  test("keeps only the numbers", () => {
    expect(
      buildBestOfSettings({
        default: 3,
        final: null,
        by_round: { "1": 5, "2": undefined as unknown as number }
      })
    ).toEqual({ default: 3, by_round: { "1": 5 } });
  });
});

describe("getStageStatus", () => {
  test("a generated but unpublished stage reads Preview, not Draft", () => {
    const s = stage({ id: 1, stage_type: "swiss" });
    expect(getStageStatus(s, false)).toBe("Draft");
    expect(getStageStatus(s, true)).toBe("Preview");
    expect(getStageStatus({ ...s, is_active: true }, true)).toBe("Active");
    expect(getStageStatus({ ...s, is_completed: true }, true)).toBe("Completed");
  });
});
