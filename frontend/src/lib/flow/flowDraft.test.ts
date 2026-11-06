import { describe, expect, it } from "vitest";

import { starterRead, port } from "./fixtures";
import {
  addNode,
  assignStageOrders,
  canDelete,
  connect,
  deletedLifecycleNodes,
  draftFromRead,
  isDirty,
  keyedValidation,
  refreshDraft,
  reconnect,
  removeNode,
  toChanges,
  updateNode,
  type FlowDraft
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

  it("moves a saved edge by deleting it and sending the new one", () => {
    const draft = addNode(draftFromRead(starterRead()), filter);
    const moved = reconnect(draft, "e10", { source: "1", sourceHandle: "participants", target: "new-1", targetHandle: "ranking" });
    const changes = toChanges(moved);
    expect(changes.delete_edge_ids).toEqual([10]);
    expect(changes.edges).toEqual([{ source: 1, source_port: "participants", target: "new-1", target_port: "ranking" }]);
  });

  it("leaves the draft as is when an edge is dropped back on its ports or onto a self-loop", () => {
    const draft = draftFromRead(starterRead());
    expect(reconnect(draft, "e10", { source: "1", sourceHandle: "participants", target: "2", targetHandle: "players" })).toBe(draft);
    expect(reconnect(draft, "e10", { source: "1", sourceHandle: "participants", target: "1", targetHandle: "participants" })).toBe(draft);
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

  describe("refetch while dirty", () => {
    const edited = () => updateNode(draftFromRead(starterRead()), "2", { config: { mode: "draft" } });
    const serverRead = (over: { reg?: Record<string, unknown>; form?: Record<string, unknown>; formName?: string }) => {
      const read = starterRead();
      read.nodes[0].config = { ...read.nodes[0].config, ...over.reg };
      read.nodes[1].config = { ...read.nodes[1].config, ...over.form };
      if (over.formName) read.nodes[1].name = over.formName;
      return read;
    };

    it("adopts the server's config into nodes the admin did not touch, so Save does not send them", () => {
      const next = refreshDraft(edited(), serverRead({ reg: { check_in: true } }));
      expect(next.nodes.find((n) => n.key === "1")?.config).toEqual({ check_in: true });
      expect(toChanges(next).nodes.map((n) => n.id)).toEqual([2]);
    });

    it("keeps the admin's edit and flags the node when the server changed the same config", () => {
      const next = refreshDraft(edited(), serverRead({ form: { mode: "manual" } }));
      const node = next.nodes.find((n) => n.key === "2")!;
      expect(node.config).toEqual({ mode: "draft" });
      expect(node.serverChanged).toBe(true);
      expect(next.nodes.find((n) => n.key === "1")?.serverChanged).toBe(false);
      expect(toChanges(next).nodes).toEqual([expect.objectContaining({ id: 2, config: { mode: "draft" } })]);
    });

    it("does not flag a node whose server config already equals the admin's edit", () => {
      const next = refreshDraft(edited(), serverRead({ form: { mode: "draft" } }));
      expect(next.nodes.find((n) => n.key === "2")?.serverChanged).toBe(false);
    });

    it("flags a renamed node the server renamed too, and keeps the flag across a later refetch", () => {
      const renamed = updateNode(draftFromRead(starterRead()), "2", { name: "Mine" });
      const once = refreshDraft(renamed, serverRead({ formName: "Theirs" }));
      expect(once.nodes.find((n) => n.key === "2")).toMatchObject({ name: "Mine", serverChanged: true });
      const twice = refreshDraft(once, serverRead({ formName: "Theirs" }));
      expect(twice.nodes.find((n) => n.key === "2")?.serverChanged).toBe(true);
    });
  });

  describe("stage phases", () => {
    const stage = (name: string, order?: number) => ({
      kind: "stage" as const,
      name,
      config: {},
      stage: { name, stage_type: "round_robin", ...(order === undefined ? {} : { order }) } as never,
      x: 0,
      y: 0
    });
    const link = (d: FlowDraft, source: string, target: string, port = "participants") =>
      connect(d, { source, sourceHandle: "ranking", target, targetHandle: port });

    it("puts a palette stage after every other stage, and the first at 0", () => {
      const first = assignStageOrders(addNode(draftFromRead(starterRead()), stage("Groups")), new Map());
      expect(first.nodes.at(-1)?.stage?.order).toBe(0);
      const second = assignStageOrders(addNode(first, stage("Playoff")), new Map());
      expect(second.nodes.at(-1)?.stage?.order).toBe(1);
      const afterSaved = assignStageOrders(addNode(draftFromRead(starterRead()), stage("Late")), new Map());
      expect(afterSaved.nodes.at(-1)?.stage?.order).toBe(0);
    });

    it("counts saved stages in, by their id", () => {
      const read = starterRead();
      (read.nodes as unknown[]).push({ id: 3, kind: "stage", name: "Groups", status: "draft", config: {}, stage_id: 40, position_x: 0, position_y: 0, ports: [] });
      const draft = assignStageOrders(addNode(draftFromRead(read), stage("Playoff")), new Map([[40, 3]]));
      expect(draft.nodes.at(-1)?.stage?.order).toBe(4);
    });

    it("follows the stages feeding it, through filters", () => {
      let d = addNode(draftFromRead(starterRead()), stage("Groups", 2));
      d = addNode(d, { kind: "filter", name: "Top", config: {}, x: 0, y: 0 });
      d = addNode(d, stage("Playoff", 0));
      d = link(d, "new-1", "new-2");
      d = link(d, "new-2", "new-3");
      expect(assignStageOrders(d, new Map()).nodes.find((n) => n.key === "new-3")?.stage?.order).toBe(3);
    });

    it("survives a cycle of stages", () => {
      let d = addNode(addNode(draftFromRead(starterRead()), stage("A", 1)), stage("B", 1));
      d = link(link(d, "new-1", "new-2"), "new-2", "new-1");
      expect(() => assignStageOrders(d, new Map())).not.toThrow();
    });
  });

  it("lists the saved lifecycle nodes a draft deletes", () => {
    let draft = addNode(draftFromRead(starterRead()), filter);
    draft = removeNode(removeNode(removeNode(draft, "new-1"), "2"), "1");
    expect(deletedLifecycleNodes(draft).map((n) => n.key)).toEqual(["1", "2"]);
    const pure = draftFromRead(starterRead());
    pure.nodes[1].kind = "filter" as never;
    pure.base = pure.nodes;
    expect(deletedLifecycleNodes(removeNode(pure, "2"))).toEqual([]);
  });
});
