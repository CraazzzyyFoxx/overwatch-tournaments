import { describe, expect, it } from "vitest";

import type { FlowRead } from "@/types/flow.types";

import { bracketBranches, branchOf } from "./branches";

type N = [id: number, kind: string, name: string, stageId?: number];
function flow(nodes: N[], edges: [number, number][]): FlowRead {
  return {
    nodes: nodes.map(([id, kind, name, stageId]) => ({
      id,
      kind,
      name,
      stage_id: stageId ?? null,
      status: "draft",
      config: {},
      ports: [],
      position_x: 0,
      position_y: 0
    })),
    edges: edges.map(([s, t], i) => ({
      id: 100 + i,
      source_node_id: s,
      source_port: "out",
      target_node_id: t,
      target_port: "in"
    })),
    results: [],
    participants: []
  } as unknown as FlowRead;
}

const league = flow(
  [
    [1, "registration", "Day 1"],
    [2, "formation", "T1"],
    [3, "stage", "Day 1", 31],
    [4, "registration", "Day 2"],
    [5, "formation", "T2"],
    [6, "stage", "Day 2", 32],
    [7, "aggregate", "Season"],
    [8, "filter", "Top 8"],
    [9, "formation", "Final teams"],
    [10, "stage", "Final", 33]
  ],
  [
    [1, 2],
    [2, 3],
    [4, 5],
    [5, 6],
    [3, 7],
    [6, 7],
    [7, 8],
    [8, 9],
    [9, 10]
  ]
);

describe("bracket branches", () => {
  it("one intake is one branch, so no branch row", () => {
    expect(
      bracketBranches(
        flow(
          [
            [1, "registration", "R"],
            [2, "formation", "T"],
            [3, "stage", "G", 31],
            [4, "filter", "F"],
            [5, "stage", "P", 32]
          ],
          [
            [1, 2],
            [2, 3],
            [3, 4],
            [4, 5]
          ]
        )
      )
    ).toEqual([]);
    expect(bracketBranches(undefined)).toEqual([]);
  });

  it("each day of a league is its own branch, labelled by its registration", () => {
    expect(bracketBranches(league).slice(0, 2)).toEqual([
      { key: "1", label: "Day 1", stageIds: [31] },
      { key: "4", label: "Day 2", stageIds: [32] }
    ]);
  });

  it("a stage fed by several intakes forms a combined branch after them", () => {
    expect(bracketBranches(league)[2]).toEqual({
      key: "1,4",
      label: "Day 1 + Day 2",
      stageIds: [33]
    });
  });

  it("finds the branch of a stage", () => {
    expect(branchOf(bracketBranches(league), 32)?.key).toBe("4");
    expect(branchOf(bracketBranches(league), null)).toBeNull();
  });
});
