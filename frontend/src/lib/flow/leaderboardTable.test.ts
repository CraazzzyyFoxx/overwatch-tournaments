import { describe, expect, it } from "vitest";

import { leagueFlow, roleFlow } from "./fixtures";
import {
  buildLeaderboardTable,
  describeAggregate,
  filterRows,
  formulaInWords,
  parseTableView,
  serializeTableView,
  sortRows
} from "./leaderboardTable";

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
      { place: 1, score: 3, counted: true, role: null, teamId: null, wins: null, draws: null, losses: null, buchholz: null },
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

describe("a by-role table", () => {
  const table = buildLeaderboardTable(roleFlow())!;
  const inRole = (role: string | null) => table.rows.filter((r) => r.role === role);

  it("lists the role partitions present, the no-role one last", () => {
    expect([table.byRole, table.roles]).toEqual([true, ["tank", "damage", null]]);
  });

  it("orders role codes through the given catalog order", () => {
    const order = (codes: Iterable<string>) => [...new Set(codes)].sort().reverse();
    expect(buildLeaderboardTable(roleFlow(), undefined, order)!.roles).toEqual(["tank", "damage", null]);
    expect(buildLeaderboardTable(roleFlow(), undefined, (c) => [...new Set(c)].sort())!.roles).toEqual([
      "damage",
      "tank",
      null
    ]);
  });

  it("keeps one row per member and role, each with its own total and cells", () => {
    const ann = table.rows.filter((r) => r.name === "Ann");
    expect(ann.map((r) => [r.role, r.total, r.key])).toEqual([
      ["tank", 6, "m1|tank"],
      ["damage", 4, "m1|damage"]
    ]);
    expect(ann[0].cells.map((c) => c?.score ?? null)).toEqual([6, null]);
    expect(ann[1].cells.map((c) => c?.score ?? null)).toEqual([null, 4]);
  });

  it("restarts places in each role and ties by (role, tie group)", () => {
    expect(inRole("tank").map((r) => [r.name, r.place, r.tied])).toEqual([
      ["Ann", 1, true],
      ["Bob", 1, true]
    ]);
    expect(inRole("damage").map((r) => [r.name, r.place, r.tied])).toEqual([["Ann", 1, false]]);
    expect(inRole(null).map((r) => [r.name, r.place, r.tied])).toEqual([["Cid", 1, false]]);
  });

  it("reads the day's role, team and metrics from the breakdown and tolerates their absence", () => {
    expect(inRole("tank")[0].cells[0]).toEqual({
      place: 1,
      score: 6,
      counted: true,
      role: "tank",
      teamId: 100,
      wins: 3,
      draws: 0,
      losses: 1,
      buchholz: 7
    });
    expect(inRole("damage")[0].cells[1]).toMatchObject({ role: "damage", wins: 2, draws: 1, buchholz: null });
    expect(inRole(null)[0].cells[0]).toMatchObject({ role: null, teamId: null, wins: null });
  });

  it("names a day's team from the participants", () => {
    expect(table.teamNames.get(100)).toBe("Rockets");
  });

  it("a leaderboard without by_role is not by role", () => {
    expect(buildLeaderboardTable(leagueFlow())).toMatchObject({ byRole: false, roles: [] });
  });
});

describe("a table that is not by role", () => {
  it("derives a row's roles from its day cells, in the given order", () => {
    const flow = leagueFlow();
    flow.results = flow.results.map((r) =>
      r.node_id === 20 && r.workspace_member_id === 1
        ? {
            ...r,
            breakdown: (r.breakdown as { node_id: number }[]).map((e, i) => ({
              ...e,
              role: ["support", "tank", "support"][i]
            }))
          }
        : r
    ) as typeof flow.results;
    const rows = buildLeaderboardTable(flow, undefined, (c) => [...new Set(c)].sort())!.rows;
    expect(rows.map((r) => [r.name, r.role, r.roles])).toEqual([
      ["Ann", null, ["support", "tank"]],
      ["Bob", null, []],
      ["Cid", null, []]
    ]);
  });
});

describe("table view", () => {
  const rows = buildLeaderboardTable(leagueFlow())!.rows;
  const { columns } = buildLeaderboardTable(leagueFlow())!;
  const byRole = buildLeaderboardTable(roleFlow())!;

  it("filters by a case-insensitive part of the name", () => {
    expect(filterRows(rows, " bO ").map((r) => r.name)).toEqual(["Bob"]);
    expect(filterRows(rows, "").length).toBe(3);
    expect(filterRows(rows, "zz")).toEqual([]);
  });

  it("sorts by a column without renumbering places", () => {
    expect(sortRows(rows, columns, "place", "desc").map((r) => [r.name, r.place])).toEqual([
      ["Cid", 3],
      ["Bob", 2],
      ["Ann", 1]
    ]);
    expect(sortRows(rows, columns, "name", "desc").map((r) => r.name)).toEqual(["Cid", "Bob", "Ann"]);
    expect(sortRows(rows, columns, "total", "asc").map((r) => r.total)).toEqual([3, 6, 9]);
  });

  it("sorts a day column with missing cells last in both directions", () => {
    const day2 = "d12";
    expect(sortRows(rows, columns, day2, "asc").map((r) => r.name)).toEqual(["Ann", "Bob", "Cid"]);
    expect(sortRows(rows, columns, day2, "desc").map((r) => r.name)).toEqual(["Ann", "Bob", "Cid"]);
    expect(sortRows(rows, columns, "d11", "asc").map((r) => r.name)).toEqual(["Bob", "Ann", "Cid"]);
    expect(sortRows(rows, columns, "d11", "desc").map((r) => r.name)).toEqual(["Ann", "Cid", "Bob"]);
  });

  it("falls back to the defaults for anything unknown", () => {
    expect(parseTableView({ role: "healer", sort: "d99", dir: "up", q: "an" }, byRole)).toEqual({
      role: "tank",
      query: "an",
      sort: "place",
      dir: "asc"
    });
    expect(parseTableView({ role: "none", sort: "total" }, byRole)).toEqual({
      role: null,
      query: "",
      sort: "total",
      dir: "desc"
    });
    expect(parseTableView({ role: "damage" }, buildLeaderboardTable(leagueFlow())!).role).toBeNull();
  });

  it("writes only what differs from the defaults and reads it back", () => {
    expect(serializeTableView(parseTableView({}, byRole), byRole)).toEqual({ role: null, q: null, sort: null, dir: null });
    const view = parseTableView({ role: "none", q: "ci", sort: "d11", dir: "asc" }, byRole);
    const written = serializeTableView(view, byRole);
    expect(written).toEqual({ role: "none", q: "ci", sort: "d11", dir: "asc" });
    expect(parseTableView(written, byRole)).toEqual(view);
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
