import { describe, expect, it } from "vitest";

import { starterRead, port } from "./fixtures";
import {
  addNode,
  canDelete,
  connect,
  draftFromRead,
  isDirty,
  keyedValidation,
  refreshDraft,
  removeNode,
  toChanges,
  updateNode
} from "./flowDraft";

const EMPTY = { nodes: [], edges: [], delete_node_ids: [], delete_edge_ids: [] };
const filter = { kind: "filter" as const, name: "Top", config: { mode: "top", n: 2 }, x: 520, y: 0 };

describe("flow draft", () => {
  it("keys saved nodes by id, keeps their status and starts clean", () => {
    const draft = draftFromRead(starterRead({ regStatus: "open" }));
    expect(draft.nodes.map((n) => [n.key, n.kind, n.status])).toEqual([
      ["1", "registration", "open"],
      ["2", "formation", "draft"]
    ]);
    expect(draft.edges.map((e) => [e.key, e.source, e.sourcePort, e.target, e.targetPort])).toEqual([
      ["e10", "1", "participants", "2", "players"]
    ]);
    expect(isDirty(draft)).toBe(false);
    expect(toChanges(draft)).toEqual(EMPTY);
  });

  it("sends a new node by ref and its edge by saved id and ref", () => {
    let draft = addNode(draftFromRead(starterRead()), {
      kind: "stage",
      name: "Groups",
      config: {},
      stage: { name: "Groups", stage_type: "round_robin" },
      x: 520,
      y: 0
    });
    draft = connect(draft, { source: "2", sourceHandle: "teams", target: "new-1", targetHandle: "participants" });
    expect(toChanges(draft)).toEqual({
      nodes: [
        { ref: "new-1", kind: "stage", name: "Groups", config: {}, stage: { name: "Groups", stage_type: "round_robin" }, position_x: 520, position_y: 0 }
      ],
      edges: [{ source: 2, source_port: "teams", target: "new-1", target_port: "participants" }],
      delete_node_ids: [],
      delete_edge_ids: []
    });
  });

  it("upserts a saved node only while it differs from what was read", () => {
    const changed = updateNode(draftFromRead(starterRead()), "2", { config: { mode: "draft" } });
    expect(toChanges(changed).nodes).toEqual([
      { id: 2, kind: "formation", name: "Teams", config: { mode: "draft" }, stage_id: null, position_x: 260, position_y: 0 }
    ]);
    expect(isDirty(updateNode(changed, "2", { config: { mode: "balancer" } }))).toBe(false);
  });

  it("deleting a saved node deletes its saved edges and drops its new ones", () => {
    let draft = addNode(draftFromRead(starterRead()), filter);
    draft = connect(draft, { source: "1", sourceHandle: "participants", target: "new-1", targetHandle: "ranking" });
    const changes = toChanges(removeNode(draft, "1"));
    expect(changes.delete_node_ids).toEqual([1]);
    expect(changes.delete_edge_ids).toEqual([10]);
    expect(changes.edges).toEqual([]);
    expect(changes.nodes.map((n) => n.ref)).toEqual(["new-1"]);
  });

  it("refuses self-loops and duplicate edges", () => {
    const draft = draftFromRead(starterRead());
    expect(connect(draft, { source: "1", sourceHandle: "participants", target: "1", targetHandle: "participants" })).toBe(draft);
    expect(connect(draft, { source: "1", sourceHandle: "participants", target: "2", targetHandle: "players" })).toBe(draft);
  });

  it("keeps a dirty draft across a refetch but takes the new statuses", () => {
    const dirty = updateNode(draftFromRead(starterRead()), "2", { name: "Day 1 teams" });
    const next = refreshDraft(dirty, starterRead({ regStatus: "open" }));
    expect(next.nodes.find((n) => n.key === "1")?.status).toBe("open");
    expect(next.nodes.find((n) => n.key === "2")?.name).toBe("Day 1 teams");
    expect(isDirty(next)).toBe(true);
  });

  it("replaces a clean draft, or none, on refetch", () => {
    expect(refreshDraft(draftFromRead(starterRead()), starterRead({ formStatus: "forming" })).nodes[1].status).toBe("forming");
    expect(refreshDraft(null, starterRead())).toEqual(draftFromRead(starterRead()));
  });

  it("maps validation ids back to node and edge keys", () => {
    let draft = addNode(draftFromRead(starterRead()), filter);
    draft = connect(draft, { source: "new-1", sourceHandle: "passed", target: "2", targetHandle: "players" });
    const keyed = keyedValidation(
      draft,
      [
        { code: "port_taken", severity: "error", message: "taken", node_id: null, edge_id: -1 },
        { code: "missing_input", severity: "warning", message: "no input", node_id: -1, edge_id: null },
        { code: "cycle", severity: "error", message: "cycle", node_id: null, edge_id: null }
      ] as never,
      [{ node_id: -1, ports: [port("ranking", "in", "players"), port("passed", "out", "players")] }] as never,
      { "new-1": -1 },
      [-1]
    );
    expect(keyed.edgeIssues.get("new-e2")?.map((i) => i.code)).toEqual(["port_taken"]);
    expect(keyed.nodeIssues.get("new-1")?.map((i) => i.code)).toEqual(["missing_input"]);
    expect(keyed.general.map((i) => i.code)).toEqual(["cycle"]);
    expect(keyed.ports.get("new-1")?.map((p) => p.name)).toEqual(["ranking", "passed"]);
  });

  it("lets only unsaved, pure and still-draft lifecycle nodes be deleted", () => {
    const draft = addNode(draftFromRead(starterRead({ regStatus: "open" })), filter);
    expect(draft.nodes.map((n) => [n.key, canDelete(n)])).toEqual([
      ["1", false],
      ["2", true],
      ["new-1", true]
    ]);
  });
});
