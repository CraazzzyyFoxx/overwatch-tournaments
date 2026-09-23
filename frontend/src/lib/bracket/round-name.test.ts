import { describe, expect, it } from "vitest";

import {
  bracketRoundLabel,
  bracketRoundLabelEn,
  withoutUpperPrefix,
  UNKNOWN_ROUND_SHAPE,
  type BracketRoundShape
} from "./round-name";

/**
 * An 8-team double elimination, as `double_elimination.generate` builds it:
 * upper 1..3, lower -1..-4, grand final 4.
 */
const DOUBLE: BracketRoundShape = {
  rounds: [1, 2, 3, -1, -2, -3, -4, 4],
  finalRounds: [4]
};

describe("bracket round names", () => {
  it("names a double elimination the way the generator does", () => {
    expect(DOUBLE.rounds.map((round) => bracketRoundLabelEn(round, DOUBLE))).toEqual([
      "UB Round 1",
      "UB Semifinal",
      "UB Final",
      "LB Round 1",
      "LB Round 2",
      "LB Round 3",
      "LB Final",
      "Grand Final"
    ]);
  });

  it("names the rematch of a grand final a reset", () => {
    const withReset: BracketRoundShape = {
      rounds: [...DOUBLE.rounds, 5],
      finalRounds: [4, 5]
    };

    expect(bracketRoundLabelEn(5, withReset)).toBe("Grand Final Reset");
    // The upper bracket's own final stays the UB Final: both trailing rounds
    // are finals, and neither steals the name of the round that feeds them.
    expect(bracketRoundLabelEn(3, withReset)).toBe("UB Final");
  });

  it("leaves a single elimination flat — it has one bracket to name", () => {
    const single: BracketRoundShape = { rounds: [1, 2, 3], finalRounds: [] };

    expect(single.rounds.map((round) => bracketRoundLabelEn(round, single))).toEqual([
      "Round 1",
      "Round 2",
      "Round 3"
    ]);
  });

  it("drops the UB prefix for the tree, and keeps LB", () => {
    const bare = (round: number) => withoutUpperPrefix(bracketRoundLabel(round, DOUBLE));

    expect(bare(1)).toEqual({ key: "round", n: 1 });
    expect(bare(2)).toEqual({ key: "semifinal" });
    expect(bare(3)).toEqual({ key: "final" });
    expect(bare(-4)).toEqual({ key: "lowerFinal", n: 4 });
    expect(bare(4)).toEqual({ key: "grandFinal" });
  });

  it("never promotes a round to a final on a guess", () => {
    // The map-pool page names rounds with no bracket in hand.
    expect(bracketRoundLabelEn(3, UNKNOWN_ROUND_SHAPE)).toBe("Round 3");
    expect(bracketRoundLabelEn(-2, UNKNOWN_ROUND_SHAPE)).toBe("LB Round 2");
  });

  it("keeps a round the bracket does not have out of both brackets", () => {
    // A stale `by_round` key past the grand final: it changes matches, so the
    // editor lists it, but calling it "UB Round 6" would invent a round.
    expect(bracketRoundLabelEn(6, DOUBLE)).toBe("Round 6");
    expect(bracketRoundLabelEn(-9, DOUBLE)).toBe("LB Round 9");
  });

  it("calls the only round of a two-team double elimination the UB Final", () => {
    // `generate([a, b])` emits rounds [1, 2]: UB Final, then the grand final.
    const twoTeams: BracketRoundShape = { rounds: [1, 2], finalRounds: [2] };

    expect(bracketRoundLabelEn(1, twoTeams)).toBe("UB Final");
    expect(bracketRoundLabelEn(2, twoTeams)).toBe("Grand Final");
  });
});
