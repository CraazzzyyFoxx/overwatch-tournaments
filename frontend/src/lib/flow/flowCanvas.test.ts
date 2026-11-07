import { describe, expect, it } from "vitest";

import { starterRead } from "@/test/flow-fixtures";

import { portsFromRead, toCanvas } from "./flowCanvas";
import { draftFromRead, keyedValidation } from "./flowDraft";
import { UNIT_COLOR } from "./kinds";

describe("flow canvas", () => {
  it("draws one handle per resolved port and colours edges by unit", () => {
    const read = starterRead();
    const draft = draftFromRead(read);
    const keyed = keyedValidation(draft, [], portsFromRead(read));
    const { nodes, edges } = toCanvas(draft, keyed.ports, new Map(), new Set(), false);
    expect(nodes.map((n) => [n.id, n.type, n.data.ports.map((p) => p.name)])).toEqual([
      ["1", "flowNode", ["participants"]],
      ["2", "flowNode", ["players", "teams"]]
    ]);
    expect(edges).toMatchObject([
      {
        id: "e10",
        source: "1",
        sourceHandle: "participants",
        target: "2",
        targetHandle: "players",
        style: { stroke: UNIT_COLOR.players }
      }
    ]);
  });

  it("marks issues on nodes and invalid edges, and freezes everything read-only", () => {
    const draft = draftFromRead(starterRead({ regStatus: "open" }));
    const { nodes, edges } = toCanvas(
      draft,
      new Map(),
      new Map([["2", 2]]),
      new Set(["e10"]),
      true
    );
    expect(nodes.map((n) => [n.id, n.data.issueCount, n.deletable])).toEqual([
      ["1", 0, false],
      ["2", 2, false]
    ]);
    expect(edges[0]).toMatchObject({ data: { invalid: true } });
  });
});
