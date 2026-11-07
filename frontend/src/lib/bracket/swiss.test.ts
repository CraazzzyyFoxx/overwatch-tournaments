import { describe, expect, it } from "vitest";

import type { Encounter } from "@/types/encounter.types";
import type { StageSummary } from "@/types/tournament.types";

import { projectedSwissEncounters, swissEncountersToCome, swissPools } from "./swiss";
import { buildRoundGroups, type BracketMatch } from "./view";

function match(
  id: number,
  round: number,
  home: number,
  away: number,
  score?: [number, number]
): BracketMatch {
  return {
    id,
    round,
    status: score ? "completed" : "open",
    teams: [
      { slot: 1, team_id: home, name: `T${home}`, score: score?.[0] ?? 0 },
      { slot: 2, team_id: away, name: `T${away}`, score: score?.[1] ?? 0 }
    ]
  };
}

const poolsOf = (matches: BracketMatch[]) =>
  swissPools(buildRoundGroups(matches)).rounds.map((round) =>
    round.pools.map((pool) => [pool.label, pool.matches.map((entry) => entry.id)])
  );

describe("swissPools", () => {
  it("splits a round by the record its teams brought in, best pool first", () => {
    expect(
      poolsOf([
        match(1, 1, 1, 2, [2, 0]),
        match(2, 1, 3, 4, [0, 2]),
        match(3, 2, 2, 3), // both 0-1
        match(4, 2, 1, 4) // both 1-0
      ])
    ).toEqual([
      [["0-0", [1, 2]]],
      [
        ["1-0", [4]],
        ["0-1", [3]]
      ]
    ]);
  });

  // Monrad floats a team down when its own pool cannot pair it; the match
  // belongs to the better pool, and the floater's record is reported.
  it("puts a float match in its better team's pool and names the floater's record", () => {
    const result = swissPools(
      buildRoundGroups([
        match(1, 1, 1, 2, [2, 0]),
        match(2, 1, 3, 4, [2, 0]),
        match(3, 2, 1, 3, [2, 0]), // 1 → 2-0
        match(4, 2, 2, 4, [2, 0]), // 2 → 1-1
        match(5, 3, 2, 1) // 1-1 against 2-0
      ])
    );
    expect(result.rounds[2].pools.map((pool) => pool.label)).toEqual(["2-0"]);
    expect(result.floats.get(5)).toEqual({ slot: 1, label: "1-1" });
  });

  it("scores a sat-out round as a bye win, round one included", () => {
    expect(
      poolsOf([
        match(1, 1, 1, 2, [2, 0]), // team 3 sits round 1 out
        match(2, 2, 3, 1), // both 1-0
        match(3, 3, 2, 3)
      ])[1]
    ).toEqual([["1-0", [2]]]);
  });

  it("switches every label to W-D-L once the stage has a draw", () => {
    expect(
      poolsOf([
        match(1, 1, 1, 2, [1, 1]),
        match(2, 1, 3, 4, [2, 0]),
        match(3, 2, 1, 2),
        match(4, 2, 3, 4)
      ])[1]
    ).toEqual([
      ["1-0-0", [4]],
      ["0-1-0", [3]]
    ]);
  });
});

// The same cases as tournament-service `ProjectedEncountersTests`: the two twins must agree.
describe("projectedSwissEncounters", () => {
  it("pairs the whole field every round without thresholds, a full circle being a round robin", () => {
    expect(projectedSwissEncounters(10, 5, null, null)).toBe(25);
    expect(projectedSwissEncounters(9, 5, null, null)).toBe(20);
    expect(projectedSwissEncounters(8, 10, null, null)).toBe(28);
    expect(projectedSwissEncounters(7, 10, null, null)).toBe(21);
  });

  it("replays the record groups under thresholds", () => {
    expect(projectedSwissEncounters(16, 5, 3, 3)).toBe(33);
    expect(projectedSwissEncounters(8, 5, 2, 2)).toBe(10);
    expect(projectedSwissEncounters(16, 3, 3, 3)).toBe(24);
  });
});

describe("swissEncountersToCome", () => {
  const stage = (id: number, extra: Partial<StageSummary> = {}) =>
    ({
      id,
      stage_type: "swiss",
      status: "live",
      max_rounds: 5,
      swiss_qualify_wins: null,
      swiss_eliminate_losses: null,
      ...extra
    }) as StageSummary;
  const encounter = (stageId: number, itemId: number | null, round: number, teams: number[]) =>
    ({
      stage_id: stageId,
      stage_item_id: itemId,
      round,
      teams: teams.map((team_id, index) => ({ slot: index + 1, team_id }))
    }) as Encounter;

  it("adds each started scope's undrawn rounds", () => {
    // Round 1 of ten teams in item 1 (25 in all), round 1 of four in item 2 (6 in all, a circle).
    const encounters = [
      ...[0, 2, 4, 6, 8].map((t) => encounter(1, 1, 1, [t, t + 1])),
      encounter(1, 2, 1, [20, 21]),
      encounter(1, 2, 1, [22, 23])
    ];
    expect(swissEncountersToCome([stage(1)], encounters)).toBe(25 - 5 + (6 - 2));
  });

  it("projects nothing for a completed stage, nor for an unstarted or non-Swiss one", () => {
    const encounters = [encounter(1, null, 1, [1, 2]), encounter(2, null, 1, [3, 4])];
    expect(
      swissEncountersToCome(
        [
          stage(1, { status: "completed" }),
          stage(2, { stage_type: "single_elimination" }),
          stage(3)
        ],
        encounters
      )
    ).toBe(0);
  });

  it("plays an individual Swiss stage's round-1 lobbies every round", () => {
    const lobbies = [encounter(1, null, 1, []), encounter(1, null, 1, [])];
    expect(swissEncountersToCome([stage(1, { stage_type: "individual_swiss" })], lobbies)).toBe(
      5 * 2 - 2
    );
  });
});
