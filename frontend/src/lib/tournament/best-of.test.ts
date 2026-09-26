import { describe, expect, it } from "vitest";

import {
  BEST_OF_OPTIONS,
  buildSequenceForBestOf,
  hasPerRoundBestOf,
  resolveBestOf,
  stageBestOfRoundSections,
  type BestOfRoundSection
} from "./best-of";

/**
 * These cases are deliberately the same ones as the backend's
 * `tests/test_best_of.py` and `tests/test_veto_session.py`. The veto room runs
 * the sequence the SERVER generates, so any divergence here is a UI previewing
 * steps the captains will never be asked to take — the tests exist to catch
 * that drift, not just to exercise the functions.
 */

const playedMaps = (sequence: string[]) =>
  sequence.filter((token) => !token.startsWith("ban")).length;

describe("resolveBestOf", () => {
  it("falls back to the default", () => {
    expect(resolveBestOf({ default: 2, by_round: {}, final: null }, 4)).toBe(2);
  });

  it("prefers a by_round override over the default", () => {
    const config = { default: 3, by_round: { "1": 2 }, final: null };
    expect(resolveBestOf(config, 1)).toBe(2);
    expect(resolveBestOf(config, 2)).toBe(3);
  });

  it("lets final win only when the round is flagged final", () => {
    const config = { default: 3, by_round: { "2": 3 }, final: 5 };
    expect(resolveBestOf(config, 2, { isFinal: true })).toBe(5);
    expect(resolveBestOf(config, 2, { isFinal: false })).toBe(3);
  });

  it("ignores an unset final on a final round", () => {
    expect(resolveBestOf({ default: 3, by_round: {}, final: null }, 9, { isFinal: true })).toBe(3);
  });
});

describe("hasPerRoundBestOf", () => {
  it("is true only when some round differs from the default", () => {
    expect(hasPerRoundBestOf({ default: 3, by_round: {}, final: null })).toBe(false);
    expect(hasPerRoundBestOf({ default: 3, by_round: { "1": 2 }, final: null })).toBe(true);
    expect(hasPerRoundBestOf({ default: 3, by_round: {}, final: 5 })).toBe(true);
  });
});

describe("stageBestOfRoundSections", () => {
  const roundsOf = (sections: BestOfRoundSection[], key: string) =>
    sections.find((section) => section.key === key)?.rounds.map((row) => row.round);

  it("keeps a flat, unlabelled round list for non-bracket stages", () => {
    const sections = stageBestOfRoundSections({ stageType: "swiss", maxRounds: 4 });
    expect(sections).toHaveLength(1);
    expect(sections[0].label).toBeNull();
    expect(sections[0].rounds).toEqual([
      { round: 1, label: "Round 1" },
      { round: 2, label: "Round 2" },
      { round: 3, label: "Round 3" },
      { round: 4, label: "Round 4" }
    ]);
  });

  /**
   * Single elimination's depth is `ceil(log2(teams))`, pinned against
   * `single_elimination.generate` — the editor must not read `max_rounds` (an
   * independent planning default) as the round count.
   */
  it("derives single elimination rounds from the team count, not max_rounds", () => {
    // 8 teams -> ceil(log2(8)) = 3 rounds, regardless of an unrelated
    // max_rounds planning default.
    const sections = stageBestOfRoundSections({
      stageType: "single_elimination",
      maxRounds: 5,
      bracketTeamCount: 8
    });
    expect(roundsOf(sections, "rounds")).toEqual([1, 2, 3]);
  });

  it("falls back to max_rounds for a single elimination with no team count", () => {
    const sections = stageBestOfRoundSections({
      stageType: "single_elimination",
      maxRounds: 4
    });
    expect(roundsOf(sections, "rounds")).toEqual([1, 2, 3, 4]);
  });

  /**
   * The rounds an 8-team double elimination actually generates are
   * `[1, 2, 3]` upper, `[-1, -2, -3, -4]` lower and `4` for the Grand Final —
   * pinned against `double_elimination.generate` so a lower-bracket round can
   * never fall off the editor and become unconfigurable. The Grand Final is
   * absent on purpose: `final` owns it and outranks `by_round`.
   */
  it("splits a double elimination into upper and lower bracket rounds", () => {
    const sections = stageBestOfRoundSections({
      stageType: "double_elimination",
      maxRounds: 5,
      bracketTeamCount: 8
    });
    expect(roundsOf(sections, "upper")).toEqual([1, 2, 3]);
    expect(roundsOf(sections, "lower")).toEqual([-1, -2, -3, -4]);
    expect(sections.flatMap((section) => section.rounds).map((row) => row.round)).not.toContain(4);
  });

  it("names the deciding round of each bracket", () => {
    const sections = stageBestOfRoundSections({
      stageType: "double_elimination",
      maxRounds: 5,
      bracketTeamCount: 8
    });
    expect(sections.find((section) => section.key === "upper")?.rounds).toEqual([
      { round: 1, label: "UB Round 1" },
      { round: 2, label: "UB Semifinal" },
      { round: 3, label: "UB Final" }
    ]);
    expect(sections.find((section) => section.key === "lower")?.rounds.at(-1)).toEqual({
      round: -4,
      label: "LB Final"
    });
  });

  it("adds the two extra lower rounds split seeding creates", () => {
    // `generate(4 upper, 4 lower seeds)` produces lower rounds -1..-4, where the
    // same 4 teams with no lower seeds would only reach -2.
    expect(
      roundsOf(
        stageBestOfRoundSections({
          stageType: "double_elimination",
          maxRounds: 4,
          bracketTeamCount: 4,
          splitLowerBracket: true
        }),
        "lower"
      )
    ).toEqual([-1, -2, -3, -4]);
    expect(
      roundsOf(
        stageBestOfRoundSections({
          stageType: "double_elimination",
          maxRounds: 4,
          bracketTeamCount: 4
        }),
        "lower"
      )
    ).toEqual([-1, -2]);
  });

  it("offers no lower bracket for a two-team double elimination", () => {
    // `generate([a, b])` emits rounds [1, 2] only — UB Final and Grand Final.
    const sections = stageBestOfRoundSections({
      stageType: "double_elimination",
      maxRounds: 2,
      bracketTeamCount: 2
    });
    expect(roundsOf(sections, "upper")).toEqual([1]);
    expect(roundsOf(sections, "lower")).toBeUndefined();
  });

  it("falls back to max_rounds before any team is seeded", () => {
    const sections = stageBestOfRoundSections({
      stageType: "double_elimination",
      maxRounds: 4
    });
    // max_rounds counts the Grand Final, the upper bracket does not.
    expect(roundsOf(sections, "upper")).toEqual([1, 2, 3]);
  });

  it("surfaces a configured round the derived brackets do not cover", () => {
    const sections = stageBestOfRoundSections({
      stageType: "double_elimination",
      maxRounds: 5,
      bracketTeamCount: 8,
      configuredRounds: [2, -9, 12]
    });
    // 2 is already offered; the other two would otherwise change matches with
    // no row to show or clear them.
    expect(roundsOf(sections, "other")).toEqual([12, -9]);
  });

  it("has no extra section when every configured round is offered", () => {
    expect(
      stageBestOfRoundSections({
        stageType: "double_elimination",
        maxRounds: 5,
        bracketTeamCount: 8,
        configuredRounds: [1, -4]
      }).map((section) => section.key)
    ).toEqual(["upper", "lower"]);
  });

  it("names a stale override on a final round, instead of a bare round number", () => {
    // 4 upper teams -> upper rounds 1..2, grand final = round 3, its reset 4.
    // Leftover `by_round` keys on those (owned by `final`) and a round the
    // bracket never has land in the extras; the finals read by name so an admin
    // can recognize them, and the dead round keeps its bare number.
    const sections = stageBestOfRoundSections({
      stageType: "double_elimination",
      maxRounds: 5,
      bracketTeamCount: 4,
      splitLowerBracket: true,
      configuredRounds: [3, 4, 12]
    });
    expect(sections.find((section) => section.key === "other")?.rounds).toEqual([
      { round: 12, label: "Round 12" },
      { round: 4, label: "Grand Final Reset" },
      { round: 3, label: "Grand Final" }
    ]);
  });
});

describe("buildSequenceForBestOf", () => {
  it("reproduces the presets the editor used to hardcode", () => {
    expect(buildSequenceForBestOf(2, 4)).toEqual([
      "ban_first",
      "ban_second",
      "pick_first",
      "pick_second"
    ]);
    expect(buildSequenceForBestOf(3, 5)).toEqual([
      "ban_first",
      "ban_second",
      "pick_first",
      "pick_second",
      "decider"
    ]);
    expect(buildSequenceForBestOf(5, 7)).toEqual([
      "ban_first",
      "ban_second",
      "pick_first",
      "pick_second",
      "pick_first",
      "pick_second",
      "decider"
    ]);
  });

  it("bans the pool down to one map for Bo1", () => {
    expect(buildSequenceForBestOf(1, 5)).toEqual([
      "ban_first",
      "ban_second",
      "ban_first",
      "ban_second",
      "decider"
    ]);
  });

  it("covers Bo7, which had no preset at all", () => {
    const sequence = buildSequenceForBestOf(7, 9);
    expect(sequence).toHaveLength(9);
    expect(playedMaps(sequence)).toBe(7);
    expect(sequence[sequence.length - 1]).toBe("decider");
  });

  it("plays exactly bestOf maps and never outgrows the pool", () => {
    for (let bestOf = 1; bestOf <= 7; bestOf += 1) {
      const poolSize = bestOf + 2;
      const sequence = buildSequenceForBestOf(bestOf, poolSize);
      expect(playedMaps(sequence), `bestOf=${bestOf}`).toBe(bestOf);
      expect(sequence.length, `bestOf=${bestOf}`).toBeLessThanOrEqual(poolSize);
    }
  });

  it("drops the opening bans rather than outgrow a tight pool", () => {
    expect(buildSequenceForBestOf(3, 3)).toEqual(["pick_first", "pick_second", "decider"]);
  });

  it("clamps a series longer than the pool", () => {
    const sequence = buildSequenceForBestOf(7, 3);
    expect(sequence.length).toBeLessThanOrEqual(3);
  });

  it("yields nothing for an empty pool", () => {
    expect(buildSequenceForBestOf(3, 0)).toEqual([]);
  });

  it("has a sequence for every length the stage editor offers", () => {
    for (const bestOf of BEST_OF_OPTIONS) {
      const sequence = buildSequenceForBestOf(bestOf, bestOf + 2);
      expect(sequence.length, `Bo${bestOf}`).toBeGreaterThan(0);
      expect(playedMaps(sequence), `Bo${bestOf}`).toBe(bestOf);
    }
  });
});
