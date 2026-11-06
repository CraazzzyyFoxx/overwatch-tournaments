import { describe, expect, it } from "vitest";

import { leagueFlow } from "./fixtures";
import { buildLeaderboardTable, describeAggregate, formulaInWords } from "./leaderboardTable";

describe("leaderboard table", () => {
  it("has one column per aggregate input, in edge order, named after the input", () => {
    expect(buildLeaderboardTable(leagueFlow())?.columns).toEqual([
      { nodeId: 11, name: "Day 1" },
      { nodeId: 12, name: "Day 2" },
      { nodeId: 13, name: "Day 3" }
    ]);
  });

  it("takes order from the leaderboard and cells and totals from the aggregate", () => {
    const rows = buildLeaderboardTable(leagueFlow())!.rows;
    expect(
      rows.map((r) => [r.place, r.name, r.total, r.cells.map((c) => c?.counted ?? null)])
    ).toEqual([
      [1, "Ann", 9, [true, true, false]],
      [2, "Bob", 6, [false, true, true]],
      [3, "Cid", 3, [true, null, null]]
    ]);
  });

  it("leaves the cell of a missed input empty", () => {
    expect(buildLeaderboardTable(leagueFlow())!.rows[2].cells).toEqual([
      { place: 1, score: 3, counted: true },
      null,
      null
    ]);
  });

  it("prints a shared place for a tie group", () => {
    const rows = buildLeaderboardTable(leagueFlow({ ties: { 1: 1, 2: 1 } }))!.rows;
    expect(rows.map((r) => [r.place, r.tied])).toEqual([
      [1, true],
      [1, true],
      [3, false]
    ]);
  });

  it("a leaderboard fed straight by a stage has no input columns", () => {
    const table = buildLeaderboardTable(leagueFlow({ feed: 13 }))!;
    expect([table.aggregate, table.columns]).toEqual([null, []]);
    expect(table.rows.map((r) => r.total)).toEqual([3, 3, 0]);
  });

  it("previews an aggregate node itself", () => {
    const table = buildLeaderboardTable(leagueFlow(), 20)!;
    expect([table.node.id, table.aggregate?.id, table.rows.map((r) => r.name)]).toEqual([
      20,
      20,
      ["Ann", "Bob", "Cid"]
    ]);
  });

  it("has no table without a leaderboard", () => {
    const flow = leagueFlow();
    expect(
      buildLeaderboardTable({ ...flow, nodes: flow.nodes.filter((n) => n.id !== 21) })
    ).toBeNull();
  });

  it("marks tentative rows and falls back to the member id without a name", () => {
    const flow = leagueFlow({ state: "tentative" });
    const table = buildLeaderboardTable({ ...flow, participants: [] } as typeof flow)!;
    expect([table.final, table.rows.map((r) => [r.name, r.tentative])]).toEqual([
      false,
      [
        ["#1", true],
        ["#2", true],
        ["#3", true]
      ]
    ]);
  });

  it("describes the formula in words", () => {
    expect(
      describeAggregate({ mode: "sum_best_n", n: 2, score: { preset: "stage_points" } })
    ).toEqual({
      mode: { key: "sumBestN", n: 2 },
      score: { key: "stagePoints", table: [], formula: null }
    });
    expect(
      describeAggregate({
        mode: "sum_all",
        n: null,
        score: { preset: "placement_table", table: { "2": 18, "1": 25 } }
      }).score.table
    ).toEqual([
      ["1", 25],
      ["2", 18]
    ]);
    expect(
      describeAggregate({
        mode: "average",
        score: { preset: "formula", formula: "max(0, participants - place + 1)" }
      })
    ).toEqual({
      mode: { key: "average", n: null },
      score: { key: "formula", table: [], formula: "max(0, participants - place + 1)" }
    });
  });
});

describe("formulaInWords", () => {
  const label = (variable: string) => `<${variable}>`;

  it("names the variables and reads * as ×", () => {
    expect(formulaInWords("wins + draws * 0.5 + buchholz * 0.01", label)).toBe(
      "<wins> + <draws> × 0.5 + <buchholz> × 0.01"
    );
  });

  it("spaces + and / and leaves minus, numbers, brackets and unknown names as written", () => {
    expect(formulaInWords("max(0,participants-place+1)/2", label)).toBe(
      "max(0,<participants>-<place> + 1) / 2"
    );
    expect(formulaInWords("bonus*2", label)).toBe("bonus × 2");
  });

  it("does not touch a name that merely contains a variable", () => {
    expect(formulaInWords("placement + points_total", label)).toBe("placement + points_total");
  });
});
