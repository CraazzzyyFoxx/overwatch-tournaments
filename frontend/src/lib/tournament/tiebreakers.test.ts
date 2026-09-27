import { describe, expect, it } from "vitest";

import {
  ALL_TIEBREAKERS,
  FFA_STAT_PREFIX,
  FFA_TIEBREAKERS,
  ffaStatTiebreakers,
  formatTiebreakOrder,
  tiebreakerLabel,
  tiebreakersForStageType
} from "./tiebreakers";

const COLUMNS = [
  { key: "kills", label: "Kills" },
  { key: "deaths", label: "Deaths" }
];

/**
 * The catalog the stage editor offers has to match what the backend engine can
 * actually compute for that stage type (`_metric_value`): an FFA lobby has no
 * opponent pairing, so offering head-to-head or Buchholz there would let an
 * organizer save a tie-break order the server silently drops — and the lobby's
 * own sums exist only for the columns THAT stage records.
 */
describe("tiebreakersForStageType", () => {
  it("offers the FFA metrics and no pairing metrics on an FFA stage", () => {
    const ids = tiebreakersForStageType("ffa_league").map((metric) => metric.id);

    expect(ids).toEqual([
      "points",
      "ffa_game_wins",
      "ffa_best_placement",
      "ffa_last_placement"
    ]);
    expect(ids).not.toContain("head_to_head");
    expect(ids).not.toContain("buchholz");
    expect(ids).not.toContain("median_buchholz");
  });

  it("offers a sum for every column the stage records", () => {
    const ids = tiebreakersForStageType("ffa_league", COLUMNS).map((metric) => metric.id);

    expect(ids).toContain("ffa_stat:kills");
    expect(ids).toContain("ffa_stat:deaths");
  });

  it("offers no column sums on a duel stage", () => {
    const ids = tiebreakersForStageType("round_robin", COLUMNS).map((metric) => metric.id);

    expect(ids).toEqual(ALL_TIEBREAKERS.map((metric) => metric.id));
    expect(ids.some((id) => id.startsWith(FFA_STAT_PREFIX))).toBe(false);
  });

  it("keeps the duel catalog for every non-FFA stage type", () => {
    for (const stageType of [
      "swiss",
      "round_robin",
      "single_elimination",
      "double_elimination"
    ] as const) {
      expect(tiebreakersForStageType(stageType)).toEqual(ALL_TIEBREAKERS);
    }

    expect(tiebreakersForStageType("swiss").map((metric) => metric.id)).toEqual([
      "points",
      "head_to_head",
      "median_buchholz",
      "buchholz",
      "match_wins",
      "score_differential"
    ]);
  });

  it("never offers a placement metric on a duel stage", () => {
    const duelIds = tiebreakersForStageType("round_robin").map((metric) => metric.id);

    for (const ffa of FFA_TIEBREAKERS.filter((metric) => metric.id.startsWith("ffa_"))) {
      expect(duelIds).not.toContain(ffa.id);
    }
  });
});

describe("ffaStatTiebreakers", () => {
  it("names a sum by the column's label, not its key", () => {
    expect(ffaStatTiebreakers(COLUMNS)).toEqual([
      { id: "ffa_stat:kills", label: "Sum: Kills" },
      { id: "ffa_stat:deaths", label: "Sum: Deaths" }
    ]);
  });

  it("falls back to the key while a new column has no label yet", () => {
    expect(ffaStatTiebreakers([{ key: "damage", label: "" }])).toEqual([
      { id: "ffa_stat:damage", label: "Sum: damage" }
    ]);
  });
});

describe("tiebreakerLabel", () => {
  it("labels the FFA metrics without an i18n resolver", () => {
    expect(tiebreakerLabel("ffa_game_wins")).toBe("Game Wins");
    expect(tiebreakerLabel("ffa_best_placement")).toBe("Best Placement");
    expect(tiebreakerLabel("ffa_last_placement")).toBe("Last Placement");
  });

  it("names a column sum from the columns it is given", () => {
    expect(tiebreakerLabel("ffa_stat:kills", undefined, COLUMNS)).toBe("Sum: Kills");
    // A reader that has the order but not the stage — the public standings
    // footer — still says which column decided it.
    expect(tiebreakerLabel("ffa_stat:kills")).toBe("Sum: kills");
  });

  it("prefers the resolver and falls back to the raw id", () => {
    expect(tiebreakerLabel("ffa_game_wins", () => "Победы в играх")).toBe("Победы в играх");
    expect(tiebreakerLabel("ffa_game_wins", () => undefined)).toBe("Game Wins");
    expect(tiebreakerLabel("ffa_stat:kills", () => "Сумма: Убийства")).toBe("Сумма: Убийства");
    expect(tiebreakerLabel("who_knows")).toBe("who_knows");
  });
});

describe("formatTiebreakOrder", () => {
  it("renders an FFA order the way the server stores it", () => {
    expect(
      formatTiebreakOrder(
        ["points", "ffa_game_wins", "ffa_stat:kills", "ffa_last_placement"],
        undefined,
        COLUMNS
      )
    ).toBe("Points → Game Wins → Sum: Kills → Last Placement");
  });
});
