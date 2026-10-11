import { describe, expect, it } from "vitest";

import { swissPools } from "./swiss";
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
    score: { home: score?.[0] ?? 0, away: score?.[1] ?? 0 },
    home_team_id: home,
    away_team_id: away
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
    expect(result.floats.get(5)).toEqual({ side: "home", label: "1-1" });
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
