import { describe, expect, it } from "vitest";

import type { FlowRead } from "@/types/flow.types";

import { standingsCuts } from "./standingsCuts";

const GROUPS = { id: 31, items: [{}, {}] };
const ONE_GROUP = { id: 31, items: [{}] };

function flow(...filters: Record<string, unknown>[]): FlowRead {
  return {
    nodes: [
      { id: 3, kind: "stage", stage_id: 31, config: {} },
      ...filters.map((config, index) => ({ id: 10 + index, kind: "filter", stage_id: null, config }))
    ],
    edges: filters.map((_, index) => ({
      id: 100 + index,
      source_node_id: 3,
      source_port: "ranking",
      target_node_id: 10 + index,
      target_port: "ranking"
    }))
  } as unknown as FlowRead;
}

describe("standingsCuts", () => {
  it("cuts each group by its own override, falling back to the filter's number", () => {
    const graph = flow({ mode: "per_item_top", n: 2, upper: 1, per_item: { "7": 3 }, per_item_upper: { "7": 2 } });
    expect(standingsCuts(graph, GROUPS, 7)).toEqual({ advance: [3], upper: [2] });
    expect(standingsCuts(graph, GROUPS, 8)).toEqual({ advance: [2], upper: [1] });
  });

  it("draws an overall top only while the stage is one group", () => {
    const graph = flow({ mode: "top", n: 4 });
    expect(standingsCuts(graph, ONE_GROUP, 7)).toEqual({ advance: [4], upper: [] });
    expect(standingsCuts(graph, GROUPS, 7)).toEqual({ advance: [], upper: [] });
  });

  it("collapses repeated cuts and ignores modes that are no place boundary", () => {
    const graph = flow(
      { mode: "per_item_top", n: 4 },
      { mode: "per_item_top", n: 4 },
      { mode: "per_item_top", n: 8, upper: 8 },
      { mode: "swiss_status", swiss_status: "qualified" },
      { mode: "range", from: 5, to: 8 }
    );
    expect(standingsCuts(graph, GROUPS, 7)).toEqual({ advance: [4, 8], upper: [] });
  });

  it("draws nothing without a flow", () => {
    expect(standingsCuts(undefined, GROUPS, 7)).toEqual({ advance: [], upper: [] });
  });
});
