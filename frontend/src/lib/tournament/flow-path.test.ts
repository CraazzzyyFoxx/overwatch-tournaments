import { describe, expect, it } from "vitest";

import { firstLifecycleSuccessor, lifecycleAncestors, stepsTo, type FlowStep, type PathGraph } from "./flow-path";

/** Tournament 124's graph: registration → formation → group → filter → playoff. */
function graph(statuses: Partial<Record<number, string>> = {}): PathGraph {
  const node = (id: number, kind: string, name: string, status: string) => ({
    id,
    kind,
    name,
    status: statuses[id] ?? status
  });
  return {
    nodes: [
      node(576, "registration", "Registration", "check_in"),
      node(577, "formation", "Teams", "draft"),
      node(599, "stage", "Group", "draft"),
      node(601, "filter", "Who advances", "tentative"),
      node(600, "stage", "PlayOff", "draft")
    ],
    edges: [
      { source_node_id: 576, target_node_id: 577 },
      { source_node_id: 577, target_node_id: 599 },
      { source_node_id: 599, target_node_id: 601 },
      { source_node_id: 601, target_node_id: 600 }
    ]
  };
}

const moves = (steps: FlowStep[] | null) => steps?.map((step) => `${step.node.id}:${step.from}>${step.to}`);

describe("stepsTo", () => {
  it("closes the registration before a formation may start forming", () => {
    expect(moves(stepsTo(graph(), 577, "forming"))).toEqual(["576:check_in>closed", "577:draft>forming"]);
  });

  it("finalizes every lifecycle input, then walks the stage through ready to live", () => {
    expect(moves(stepsTo(graph({ 576: "closed", 577: "forming" }), 599, "live"))).toEqual([
      "577:forming>completed",
      "599:draft>ready",
      "599:ready>live"
    ]);
  });

  it("goes through a pure node to the lifecycle node behind it", () => {
    expect(moves(stepsTo(graph({ 576: "closed", 577: "completed", 599: "live" }), 600, "ready"))).toEqual([
      "599:live>completed",
      "600:draft>ready"
    ]);
  });

  it("plans nothing for a node already there, and null for a move the lifecycle lacks", () => {
    expect(stepsTo(graph({ 577: "forming" }), 577, "forming")).toEqual([]);
    expect(stepsTo(graph({ 599: "completed" }), 599, "ready")).toBeNull();
  });
});

describe("chain neighbours", () => {
  it("names the lifecycle nodes around one, through pure nodes", () => {
    expect(lifecycleAncestors(graph(), 600).map((node) => node.id)).toEqual([576, 577, 599]);
    expect(firstLifecycleSuccessor(graph(), 577)?.id).toBe(599);
    expect(firstLifecycleSuccessor(graph(), 599)?.id).toBe(600);
  });
});
