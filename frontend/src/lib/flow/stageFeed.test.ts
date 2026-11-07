import { describe, expect, it } from "vitest";

import type { FlowRead, FlowStageCreate } from "@/types/flow.types";

import {
  addStageChanges,
  changeStageFeed,
  classifyStageFeed,
  type FeedRule
} from "./stageFeed";

type Node = [id: number, kind: string, name: string, config?: Record<string, unknown>];
type Edge = [id: number, from: number, fromPort: string, to: number, toPort: string];

function graph(nodes: Node[], edges: Edge[]): FlowRead {
  return {
    nodes: nodes.map(([id, kind, name, config]) => ({
      id,
      kind,
      name,
      config: config ?? {},
      position_x: id * 100,
      position_y: 10
    })),
    edges: edges.map(([id, s, sp, t, tp]) => ({
      id,
      source_node_id: s,
      source_port: sp,
      target_node_id: t,
      target_port: tp
    })),
    results: [],
    participants: []
  } as unknown as FlowRead;
}

const rule = (over: Partial<FeedRule> = {}): FeedRule => ({
  mode: "top",
  n: 2,
  upper: null,
  swissStatus: "qualified",
  ...over
});

const GROUPS = 3;
const PLAYOFF = 5;
const FILTER = 4;
const filtered = (config: Record<string, unknown> = { mode: "per_item_top", n: 2 }) =>
  graph(
    [[GROUPS, "stage", "Groups"], [FILTER, "filter", "Top", config], [PLAYOFF, "stage", "Playoff"]],
    [[10, GROUPS, "ranking", FILTER, "ranking"], [11, FILTER, "passed", PLAYOFF, "participants"]]
  );
const direct = graph(
  [[GROUPS, "stage", "Groups"], [PLAYOFF, "stage", "Playoff"]],
  [[10, GROUPS, "ranking", PLAYOFF, "participants"]]
);
const unwired = graph([[GROUPS, "stage", "Groups"], [PLAYOFF, "stage", "Playoff"]], []);

describe("classifyStageFeed", () => {
  it("tells the five shapes of a stage's input apart", () => {
    expect(classifyStageFeed(unwired, PLAYOFF).kind).toBe("none");
    expect(classifyStageFeed(direct, PLAYOFF)).toEqual({ kind: "direct", sourceStageNodeId: GROUPS, edgeId: 10 });
    expect(classifyStageFeed(filtered(), PLAYOFF)).toMatchObject({
      kind: "filter",
      sourceStageNodeId: GROUPS,
      edgeIds: [10, 11]
    });
    const entry = graph(
      [[1, "registration", "Signups"], [GROUPS, "stage", "Groups"]],
      [[10, 1, "participants", GROUPS, "participants"]]
    );
    expect(classifyStageFeed(entry, GROUPS)).toEqual({ kind: "entry", sources: ["Signups"] });
    const merged = graph(
      [[1, "stage", "A"], [2, "merge", "Both"], [PLAYOFF, "stage", "Playoff"]],
      [[10, 1, "ranking", 2, "in"], [11, 2, "out", PLAYOFF, "participants"]]
    );
    expect(classifyStageFeed(merged, PLAYOFF)).toEqual({
      kind: "complex",
      sources: [{ kind: "merge", name: "Both" }]
    });
  });

  it("reads a stage fed by a formation through it, and writes the rule onto the formation's input", () => {
    const QUALIFICATION = 1;
    const FORMATION = 2;
    const reformed = graph(
      [[QUALIFICATION, "stage", "Qualification"], [FORMATION, "formation", "Formation", { mode: "draft" }], [GROUPS, "stage", "Groups"]],
      [[10, QUALIFICATION, "ranking", FORMATION, "players"], [11, FORMATION, "teams", GROUPS, "participants"]]
    );
    expect(classifyStageFeed(reformed, GROUPS)).toMatchObject({
      kind: "formed",
      formation: { id: FORMATION },
      inner: { kind: "direct", sourceStageNodeId: QUALIFICATION }
    });
    expect(changeStageFeed(reformed, GROUPS, { source: QUALIFICATION, rule: rule({ n: 20 }) }, "F")).toMatchObject({
      nodes: [{ ref: "filter", config: { mode: "top", n: 20 } }],
      edges: [
        { source: QUALIFICATION, target: "filter", target_port: "ranking" },
        { source: "filter", source_port: "passed", target: FORMATION, target_port: "players" }
      ],
      delete_edge_ids: [10]
    });

    const firstStage = graph(
      [[9, "registration", "Signups"], [FORMATION, "formation", "Formation"], [GROUPS, "stage", "Groups"]],
      [[12, 9, "participants", FORMATION, "players"], [11, FORMATION, "teams", GROUPS, "participants"]]
    );
    expect(classifyStageFeed(firstStage, GROUPS)).toMatchObject({ kind: "formed", inner: { kind: "entry", sources: ["Signups"] } });
  });

  it("leaves a filter Bracket cannot express to Flow", () => {
    for (const config of [
      { mode: "range", from: 1, to: 4 },
      { mode: "manual", manual: [1] },
      { mode: "per_item_top", n: 2, per_item: { 7: 1 } }
    ]) {
      expect(classifyStageFeed(filtered(config), PLAYOFF).kind).toBe("complex");
    }
    const shared = filtered();
    shared.edges.push({ id: 12, source_node_id: FILTER, source_port: "passed", target_node_id: 9, target_port: "participants" });
    expect(classifyStageFeed(shared, PLAYOFF).kind).toBe("complex");
  });

  it("reads per-group values equal to the general count as the plain rule", () => {
    const migrated = filtered({ mode: "per_item_top", n: 2, per_item: { 7: 2, 8: 2 }, upper: 1, per_item_upper: { 7: 1 } });
    expect(classifyStageFeed(migrated, PLAYOFF).kind).toBe("filter");
  });
});

describe("changeStageFeed", () => {
  const to = (source: number, r: FeedRule) => ({ source, rule: r });

  it("wires a direct edge for «all», a filter and two edges for a rule", () => {
    expect(changeStageFeed(unwired, PLAYOFF, to(GROUPS, rule({ mode: "all" })), "F")).toMatchObject({
      nodes: [],
      edges: [{ source: GROUPS, source_port: "ranking", target: PLAYOFF, target_port: "participants" }]
    });
    const changes = changeStageFeed(unwired, PLAYOFF, to(GROUPS, rule({ mode: "per_item_top", upper: 1 })), "F");
    expect(changes?.nodes).toEqual([
      expect.objectContaining({ ref: "filter", kind: "filter", config: { mode: "per_item_top", n: 2, upper: 1 } })
    ]);
    expect(changes?.edges).toEqual([
      expect.objectContaining({ source: GROUPS, target: "filter", target_port: "ranking" }),
      expect.objectContaining({ source: "filter", source_port: "passed", target: PLAYOFF })
    ]);
  });

  it("updates the existing filter in place and only what changed", () => {
    const base = filtered();
    expect(changeStageFeed(base, PLAYOFF, to(GROUPS, rule({ mode: "per_item_top" })), "F")).toBeNull();
    expect(changeStageFeed(base, PLAYOFF, to(GROUPS, rule({ mode: "per_item_top", n: 3 })), "F")).toEqual({
      nodes: [{ id: FILTER, kind: "filter", name: "Top", config: { mode: "per_item_top", n: 3 } }],
      edges: []
    });
    const swiss = changeStageFeed(base, PLAYOFF, to(GROUPS, rule({ mode: "swiss_status", swissStatus: "eliminated" })), "F");
    expect(swiss?.nodes?.[0].config).toEqual({ mode: "swiss_status", swiss_status: "eliminated" });
    const earlier = graph([[1, "stage", "Earlier"]], []).nodes[0];
    const moved = changeStageFeed({ ...base, nodes: [...base.nodes, earlier] }, PLAYOFF, to(1, rule({ mode: "per_item_top" })), "F");
    expect(moved).toEqual({ nodes: [], edges: [{ id: 10, source: 1, source_port: "ranking", target: FILTER, target_port: "ranking" }] });
  });

  it("swaps a filter for a direct edge and back, deleting what it replaces", () => {
    expect(changeStageFeed(filtered(), PLAYOFF, to(GROUPS, rule({ mode: "all" })), "F")).toMatchObject({
      edges: [{ source: GROUPS, target: PLAYOFF }],
      delete_edge_ids: [10, 11],
      delete_node_ids: [FILTER]
    });
    expect(changeStageFeed(direct, PLAYOFF, to(GROUPS, rule()), "F")).toMatchObject({
      nodes: [{ ref: "filter" }],
      delete_edge_ids: [10],
      delete_node_ids: []
    });
    expect(changeStageFeed(direct, PLAYOFF, to(GROUPS, rule({ mode: "all" })), "F")).toBeNull();
  });

  it("never touches an entry or a complex feed", () => {
    const merged = graph(
      [[1, "stage", "A"], [2, "merge", "Both"], [PLAYOFF, "stage", "Playoff"]],
      [[10, 1, "ranking", 2, "in"], [11, 2, "out", PLAYOFF, "participants"]]
    );
    expect(changeStageFeed(merged, PLAYOFF, to(1, rule({ mode: "all" })), "F")).toBeNull();
  });
});

describe("addStageChanges", () => {
  const stage = { name: "Playoff", stage_type: "double_elimination" } as FlowStageCreate;
  const source = graph([[GROUPS, "stage", "Groups"]], []).nodes[0];

  it("creates the stage, its filter and both edges in one change set", () => {
    const changes = addStageChanges({ name: "Playoff", stage, source, rule: rule({ mode: "per_item_top" }), filterName: "F" });
    expect(changes.nodes?.map((node) => node.ref)).toEqual(["stage", "filter"]);
    expect(changes.nodes?.[0]).toMatchObject({ kind: "stage", stage, position_x: 300 + 600, position_y: 10 });
    expect(changes.edges).toEqual([
      expect.objectContaining({ source: GROUPS, target: "filter" }),
      expect.objectContaining({ source: "filter", target: "stage", target_port: "participants" })
    ]);
  });

  it("wires «all» straight in, and a first stage with nothing", () => {
    expect(addStageChanges({ name: "P", stage, source, rule: rule({ mode: "all" }), filterName: "F" })).toMatchObject({
      nodes: [{ ref: "stage" }],
      edges: [{ source: GROUPS, target: "stage" }]
    });
    expect(addStageChanges({ name: "P", stage, source: null, rule: rule(), filterName: "F" }).edges).toBeUndefined();
  });
});
