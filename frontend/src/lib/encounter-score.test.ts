import { describe, expect, it } from "vitest";

import { getScorePresetsForBestOf, validSeriesScores } from "@/lib/encounter-score";

function labels(scores: { label: string }[]): string[] {
  return scores.map((score) => score.label);
}

describe("validSeriesScores", () => {
  it("BO1 -> 1-0, 0-1", () => {
    expect(labels(validSeriesScores(1))).toEqual(["1-0", "0-1"]);
  });

  it("BO2 -> 2-0, draw, 0-2 (even series allow a tie)", () => {
    expect(labels(validSeriesScores(2))).toEqual(["2-0", "1-1", "0-2"]);
  });

  it("BO3 -> 2-0, 2-1, 1-2, 0-2 (no draw)", () => {
    expect(labels(validSeriesScores(3))).toEqual(["2-0", "2-1", "1-2", "0-2"]);
  });

  it("BO5 -> 3-0..3-2 and mirror", () => {
    expect(labels(validSeriesScores(5))).toEqual([
      "3-0",
      "3-1",
      "3-2",
      "2-3",
      "1-3",
      "0-3"
    ]);
  });

  it("marks draws and sweeps via reused description keys", () => {
    const bo2 = validSeriesScores(2);
    expect(bo2.map((score) => score.description)).toEqual([
      "Home sweep",
      "Draw",
      "Away sweep"
    ]);
  });

  it("returns nothing for invalid series lengths", () => {
    expect(validSeriesScores(0)).toEqual([]);
    expect(validSeriesScores(-3)).toEqual([]);
    expect(validSeriesScores(2.5)).toEqual([]);
  });
});

describe("getScorePresetsForBestOf", () => {
  it("shows discrete presets for short series (BO1-BO3)", () => {
    expect(labels(getScorePresetsForBestOf(1))).toEqual(["1-0", "0-1"]);
    expect(labels(getScorePresetsForBestOf(2))).toEqual(["2-0", "1-1", "0-2"]);
    expect(labels(getScorePresetsForBestOf(3))).toEqual(["2-0", "2-1", "1-2", "0-2"]);
  });

  it("shows no presets for long series (manual entry only)", () => {
    expect(getScorePresetsForBestOf(5)).toEqual([]);
    expect(getScorePresetsForBestOf(7)).toEqual([]);
  });
});
