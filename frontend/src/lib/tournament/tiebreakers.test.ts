import { describe, expect, it } from "vitest";

import {
  ALL_TIEBREAKERS,
  FFA_TIEBREAKERS,
  formatTiebreakOrder,
  tiebreakerLabel,
  tiebreakersForStageType
} from "./tiebreakers";

/**
 * The catalog the StageManager editor offers has to match what the backend
 * engine can actually compute for that stage type (`_metric_value`): an FFA
 * lobby has no opponent pairing, so offering head-to-head or Buchholz there
 * would let an organizer save a tie-break order the server silently drops.
 */
describe("tiebreakersForStageType", () => {
  it("offers the FFA metrics and no pairing metrics on an FFA stage", () => {
    const ids = tiebreakersForStageType("ffa_league").map((metric) => metric.id);

    expect(ids).toEqual([
      "points",
      "ffa_game_wins",
      "ffa_score",
      "ffa_best_placement",
      "ffa_last_placement",
      "manual_override"
    ]);
    expect(ids).not.toContain("head_to_head");
    expect(ids).not.toContain("buchholz");
    expect(ids).not.toContain("median_buchholz");
  });

  it("keeps the duel catalog for every non-FFA stage type", () => {
    for (const stageType of ["swiss", "round_robin", "single_elimination", "double_elimination"] as const) {
      expect(tiebreakersForStageType(stageType)).toEqual(ALL_TIEBREAKERS);
    }

    expect(tiebreakersForStageType("swiss").map((metric) => metric.id)).toEqual([
      "points",
      "head_to_head",
      "median_buchholz",
      "buchholz",
      "match_wins",
      "score_differential",
      "manual_override"
    ]);
  });

  it("never offers a placement or lobby-score metric on a duel stage", () => {
    const duelIds = tiebreakersForStageType("round_robin").map((metric) => metric.id);

    for (const ffa of FFA_TIEBREAKERS.filter((metric) => metric.id.startsWith("ffa_"))) {
      expect(duelIds).not.toContain(ffa.id);
    }
  });
});

describe("tiebreakerLabel", () => {
  it("labels the FFA metrics without an i18n resolver", () => {
    expect(tiebreakerLabel("ffa_game_wins")).toBe("Game Wins");
    expect(tiebreakerLabel("ffa_score")).toBe("Score");
    expect(tiebreakerLabel("ffa_best_placement")).toBe("Best Placement");
    expect(tiebreakerLabel("ffa_last_placement")).toBe("Last Placement");
  });

  it("prefers the resolver and falls back to the raw id", () => {
    expect(tiebreakerLabel("ffa_score", () => "Очки за фраги")).toBe("Очки за фраги");
    expect(tiebreakerLabel("ffa_score", () => undefined)).toBe("Score");
    expect(tiebreakerLabel("who_knows")).toBe("who_knows");
  });
});

describe("formatTiebreakOrder", () => {
  it("renders an FFA order the way the server stores it", () => {
    expect(formatTiebreakOrder(["points", "ffa_game_wins", "ffa_last_placement"])).toBe(
      "Points → Game Wins → Last Placement"
    );
  });
});
