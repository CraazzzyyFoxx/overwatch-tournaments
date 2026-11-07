import { describe, expect, it } from "vitest";

import { starterRead } from "@/test/flow-fixtures";

import { draftFromRead, toChanges, type FlowChangeSet } from "./flowDraft";
import { applyPreset, hasOnlyStarterNodes, type PresetLabels } from "./presets";

const LABELS: PresetLabels = {
  playoff: "Playoff",
  groups: "Groups",
  topPerGroup: (n) => `Top ${n} per group`,
  top: (n) => `Top ${n}`,
  playoffTeams: "Playoff teams",
  swiss: "Swiss",
  qualifiers: "Qualifiers",
  day: (i) => `Day ${i}`,
  dayTeams: (i) => `Day ${i} teams`,
  season: "Season",
  seasonTable: "Season table"
};

const run = (preset: Parameters<typeof applyPreset>[1], params = {}) =>
  toChanges(applyPreset(draftFromRead(starterRead()), preset, params, LABELS));
const wires = (c: FlowChangeSet) => c.edges.map((e) => `${e.source}.${e.source_port}>${e.target}.${e.target_port}`);

describe("presets", () => {
  it("single stage hangs one playoff off the starter formation", () => {
    const c = run("single");
    expect(c.nodes).toEqual([
      { ref: "new-1", kind: "stage", name: "Playoff", config: {}, stage: { name: "Playoff", stage_type: "single_elimination", order: 2 }, position_x: 520, position_y: 0 }
    ]);
    expect(wires(c)).toEqual(["2.teams>new-1.participants"]);
  });

  it("groups to playoff cuts the top 2 of every group and seeds the playoff crosswise", () => {
    const c = run("groups_playoff");
    expect(c.nodes.map((n) => [n.kind, n.name, n.config])).toEqual([
      ["stage", "Groups", {}],
      ["filter", "Top 2 per group", { mode: "per_item_top", n: 2 }],
      ["stage", "Playoff", {}]
    ]);
    expect(c.nodes[2].stage).toMatchObject({ stage_type: "single_elimination", seed_ranking: "cross" });
    expect(wires(c)).toEqual(["2.teams>new-1.participants", "new-1.ranking>new-2.ranking", "new-2.passed>new-3.participants"]);
  });

  it("re-formation dissolves the qualified teams into a second formation", () => {
    const c = run("groups_reformation_playoff");
    expect(c.nodes.map((n) => [n.kind, n.name, n.config])).toEqual([
      ["stage", "Groups", {}],
      ["filter", "Top 4", { mode: "top", n: 4 }],
      ["formation", "Playoff teams", { mode: "balancer" }],
      ["stage", "Playoff", {}]
    ]);
    expect(wires(c)).toEqual([
      "2.teams>new-1.participants",
      "new-1.ranking>new-2.ranking",
      "new-2.passed>new-3.players",
      "new-3.teams>new-4.participants"
    ]);
  });

  it("individual Swiss moves the starter formation behind the qualifier filter as a draft", () => {
    const c = run("swiss_draft_playoff");
    expect(c.delete_edge_ids).toEqual([10]);
    expect(c.nodes.find((n) => n.id === 2)).toMatchObject({ config: { mode: "draft" }, position_x: 780 });
    expect(c.nodes.find((n) => n.name === "Swiss")?.stage).toMatchObject({ stage_type: "individual_swiss", playoff_team_count: 4 });
    expect(c.nodes.find((n) => n.name === "Qualifiers")?.config).toEqual({ mode: "top", n: 20 });
    expect(wires(c)).toEqual([
      "1.participants>new-1.participants",
      "new-1.ranking>new-2.ranking",
      "new-2.passed>2.players",
      "2.teams>new-3.participants"
    ]);
  });

  it("a league season has a branch per day feeding one best-K aggregate and a table", () => {
    const c = run("league", { days: 3, best: 2 });
    expect(c.nodes.find((n) => n.id === 1)?.name).toBe("Day 1");
    expect(c.nodes.filter((n) => n.kind === "registration" && n.ref).map((n) => n.name)).toEqual(["Day 2", "Day 3"]);
    expect(c.nodes.filter((n) => n.kind === "formation" && n.ref).map((n) => n.config)).toEqual([{ mode: "balancer" }, { mode: "balancer" }]);
    expect(c.nodes.find((n) => n.kind === "aggregate")?.config).toEqual({
      unit: "players",
      score: { preset: "stage_points" },
      mode: "sum_best_n",
      n: 2
    });
    const aggregate = c.nodes.find((n) => n.kind === "aggregate")!.ref;
    const board = c.nodes.find((n) => n.kind === "leaderboard")!.ref;
    expect(c.edges.filter((e) => e.target === aggregate && e.target_port === "inputs")).toHaveLength(3);
    expect(wires(c)).toContain(`${aggregate}.ranking>${board}.ranking`);
  });

  it("gives each league day a phase of its own, in day order", () => {
    const c = run("league", { days: 3, best: 2 });
    expect(c.nodes.filter((n) => n.stage).map((n) => [n.name, n.stage?.order])).toEqual([["Day 1", 1], ["Day 2", 2], ["Day 3", 3]]);
  });

  it("counts every day when best equals days, and refuses best above days and fewer than two days", () => {
    expect(run("league", { days: 2, best: 2 }).nodes.find((n) => n.kind === "aggregate")?.config).toMatchObject({ mode: "sum_all", n: null });
    expect(() => run("league", { days: 3, best: 4 })).toThrow(RangeError);
    expect(() => run("league", { days: 1, best: 1 })).toThrow(RangeError);
  });

  it("offers presets only on the untouched starter pair", () => {
    expect(hasOnlyStarterNodes(starterRead())).toBe(true);
    expect(hasOnlyStarterNodes(starterRead({ regStatus: "open" }))).toBe(false);
  });
});
