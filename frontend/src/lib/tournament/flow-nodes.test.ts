import { describe, expect, it } from "vitest";

import type { TournamentFlowNode } from "@/types/flow.types";

import { currentRegistrationNode } from "./flow-nodes";

function node(id: number, status: string, kind = "registration"): TournamentFlowNode {
  return { id, kind, name: `Node ${id}`, status, config: {}, schedule: [], stage_id: null } as TournamentFlowNode;
}

const idOf = (nodes: TournamentFlowNode[]) => currentRegistrationNode({ flow_nodes: nodes })?.id ?? null;

describe("currentRegistrationNode", () => {
  it("prefers the first open node", () => {
    expect(idOf([node(3, "check_in"), node(5, "open"), node(4, "open")])).toBe(4);
  });

  it("falls back to the first node in check-in", () => {
    expect(idOf([node(3, "closed"), node(5, "check_in"), node(4, "check_in")])).toBe(4);
  });

  it("falls back to the latest node that left draft", () => {
    expect(idOf([node(3, "closed"), node(4, "closed"), node(5, "draft")])).toBe(4);
  });

  it("is none for draft-only, formation-only or absent nodes", () => {
    expect(idOf([node(3, "draft")])).toBeNull();
    expect(idOf([node(9, "forming", "formation")])).toBeNull();
    expect(currentRegistrationNode(undefined)).toBeNull();
  });
});
