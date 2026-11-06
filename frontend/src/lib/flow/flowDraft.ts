import type {
  FlowIssueRead,
  FlowNodeKind,
  FlowNodeStatus as FlowNodeStatusValue,
  FlowNodeUpsert,
  FlowPortRead,
  FlowRead,
  FlowStageCreate
} from "@/types/flow.types";

import { isLifecycle, kindOf } from "./kinds";

export type DraftNode = {
  key: string;
  id: number | null;
  kind: FlowNodeKind;
  name: string;
  config: Record<string, unknown>;
  stageId: number | null;
  stage: FlowStageCreate | null;
  x: number;
  y: number;
  status: FlowNodeStatusValue | null;
  /** The server changed this node's name or config while the admin's edit of it was pending. */
  serverChanged?: boolean;
};

export type DraftEdge = {
  key: string;
  id: number | null;
  source: string;
  sourcePort: string;
  target: string;
  targetPort: string;
};

export type FlowDraft = {
  nodes: DraftNode[];
  edges: DraftEdge[];
  /** The saved nodes as read; `toChanges` upserts a saved node only while it differs from its entry. */
  base: DraftNode[];
  deletedNodeIds: number[];
  deletedEdgeIds: number[];
  /** One counter for new node and edge keys. */
  nextRef: number;
};

/** `FlowChanges` with what the editor sends: `nodes` always present, a new stage node carrying its `stage`. */
export type FlowNodeChange = Pick<FlowNodeUpsert, "kind" | "name" | "config" | "position_x" | "position_y"> & {
  ref?: string;
  id?: number;
  stage_id?: number | null;
  stage?: FlowStageCreate;
};
export type FlowEdgeChange = { source: number | string; source_port: string; target: number | string; target_port: string };
export type FlowChangeSet = {
  nodes: FlowNodeChange[];
  edges: FlowEdgeChange[];
  delete_node_ids: number[];
  delete_edge_ids: number[];
};

export type NewNode = {
  kind: FlowNodeKind;
  name: string;
  config: Record<string, unknown>;
  stage?: FlowStageCreate | null;
  x: number;
  y: number;
};

export type KeyedValidation = {
  nodeIssues: Map<string, FlowIssueRead[]>;
  edgeIssues: Map<string, FlowIssueRead[]>;
  general: FlowIssueRead[];
  ports: Map<string, FlowPortRead[]>;
};

function sorted(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sorted);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([a], [b]) => (a < b ? -1 : 1))
        .map(([k, v]) => [k, sorted(v)])
    );
  }
  return value;
}

const sameValue = (a: unknown, b: unknown) => JSON.stringify(sorted(a)) === JSON.stringify(sorted(b));

const readNode = (n: FlowRead["nodes"][number]): DraftNode => ({
  key: String(n.id),
  id: n.id,
  kind: kindOf(n),
  name: n.name,
  config: n.config,
  stageId: n.stage_id,
  stage: null,
  x: n.position_x,
  y: n.position_y,
  status: n.status
});

export const draftFromRead = (read: FlowRead): FlowDraft => {
  const nodes = read.nodes.map(readNode);
  return {
    nodes,
    edges: read.edges.map((e) => ({
      key: `e${e.id}`,
      id: e.id,
      source: String(e.source_node_id),
      sourcePort: e.source_port,
      target: String(e.target_node_id),
      targetPort: e.target_port
    })),
    base: nodes,
    deletedNodeIds: [],
    deletedEdgeIds: [],
    nextRef: 1
  };
};

export const addNode = (draft: FlowDraft, node: NewNode): FlowDraft => ({
  ...draft,
  nodes: [
    ...draft.nodes,
    {
      key: `new-${draft.nextRef}`,
      id: null,
      kind: node.kind,
      name: node.name,
      config: node.config,
      stageId: null,
      stage: node.stage ?? null,
      x: node.x,
      y: node.y,
      status: null
    }
  ],
  nextRef: draft.nextRef + 1
});

export const updateNode = (
  draft: FlowDraft,
  key: string,
  patch: Partial<Pick<DraftNode, "name" | "config" | "x" | "y" | "stage">>
): FlowDraft => ({ ...draft, nodes: draft.nodes.map((n) => (n.key === key ? { ...n, ...patch } : n)) });

/** Drops edges by key; a saved one is also queued for deletion. */
const dropEdges = (draft: FlowDraft, drop: (e: DraftEdge) => boolean): FlowDraft => {
  const gone = draft.edges.filter(drop);
  return {
    ...draft,
    edges: draft.edges.filter((e) => !drop(e)),
    deletedEdgeIds: [...draft.deletedEdgeIds, ...gone.flatMap((e) => (e.id === null ? [] : [e.id]))]
  };
};

export const removeEdge = (draft: FlowDraft, key: string): FlowDraft => dropEdges(draft, (e) => e.key === key);

export const removeNode = (draft: FlowDraft, key: string): FlowDraft => {
  const node = draft.nodes.find((n) => n.key === key);
  if (!node) return draft;
  const next = dropEdges(draft, (e) => e.source === key || e.target === key);
  return {
    ...next,
    nodes: next.nodes.filter((n) => n.key !== key),
    deletedNodeIds: node.id === null ? next.deletedNodeIds : [...next.deletedNodeIds, node.id]
  };
};

export const connect = (
  draft: FlowDraft,
  c: { source: string; sourceHandle: string; target: string; targetHandle: string }
): FlowDraft => {
  const duplicate = draft.edges.some(
    (e) => e.source === c.source && e.sourcePort === c.sourceHandle && e.target === c.target && e.targetPort === c.targetHandle
  );
  if (c.source === c.target || duplicate) return draft;
  return {
    ...draft,
    edges: [
      ...draft.edges,
      { key: `new-e${draft.nextRef}`, id: null, source: c.source, sourcePort: c.sourceHandle, target: c.target, targetPort: c.targetHandle }
    ],
    nextRef: draft.nextRef + 1
  };
};

/** Moves an edge to new endpoints: the old one is dropped (a saved one queued for deletion), a new one added. Unmoved, or refused by `connect`, the draft stays as is. */
export const reconnect = (
  draft: FlowDraft,
  key: string,
  c: { source: string; sourceHandle: string; target: string; targetHandle: string }
): FlowDraft => {
  const old = draft.edges.find((e) => e.key === key);
  const unmoved =
    old && old.source === c.source && old.sourcePort === c.sourceHandle && old.target === c.target && old.targetPort === c.targetHandle;
  if (!old || unmoved) return draft;
  const dropped = removeEdge(draft, key);
  const next = connect(dropped, c);
  return next === dropped ? draft : next;
};

/** Every stage node feeding `key`, reached through any chain of non-stage nodes (a stage's own upstream is already behind it). */
function upstreamStages(draft: FlowDraft, key: string): DraftNode[] {
  const found = new Map<string, DraftNode>();
  const seen = new Set([key]);
  const queue = [key];
  for (let at = queue.shift(); at !== undefined; at = queue.shift()) {
    for (const edge of draft.edges) {
      if (edge.target !== at || seen.has(edge.source)) continue;
      seen.add(edge.source);
      const source = draft.nodes.find((n) => n.key === edge.source);
      if (source?.kind === "stage") found.set(source.key, source);
      else if (source) queue.push(source.key);
    }
  }
  return [...found.values()];
}

/**
 * A new stage's `order` is its phase, so it follows the stages that feed it: 1 + the highest phase upstream. One with nothing
 * upstream yet (a palette add) takes the phase after every other stage, 0 when there is none. `savedOrders` maps a saved
 * stage's id to its phase. Run after an add or a connect; a preset sets its own orders and skips this.
 */
export function assignStageOrders(draft: FlowDraft, savedOrders: ReadonlyMap<number, number>): FlowDraft {
  const phases = new Map<string, number>();
  const visiting = new Set<string>();
  const phaseOf = (node: DraftNode): number => {
    const known = phases.get(node.key);
    if (known !== undefined) return known;
    const own = node.stageId === null ? (node.stage?.order ?? 0) : (savedOrders.get(node.stageId) ?? 0);
    if (node.stageId !== null || visiting.has(node.key)) return own;
    visiting.add(node.key);
    const upstream = upstreamStages(draft, node.key);
    const phase = upstream.length > 0 ? 1 + Math.max(...upstream.map(phaseOf)) : own;
    visiting.delete(node.key);
    phases.set(node.key, phase);
    return phase;
  };
  const others = (node: DraftNode) => draft.nodes.filter((n) => n.kind === "stage" && n.key !== node.key).map(phaseOf);
  return {
    ...draft,
    nodes: draft.nodes.map((n) => {
      if (n.kind !== "stage" || n.id !== null || !n.stage) return n;
      const upstream = upstreamStages(draft, n.key);
      const order = upstream.length > 0 ? phaseOf(n) : (n.stage.order ?? Math.max(-1, ...others(n)) + 1);
      return { ...n, stage: { ...n.stage, order } };
    })
  };
}

export const toChanges = (draft: FlowDraft): FlowChangeSet => {
  const idOf = (key: string): number | string => draft.nodes.find((n) => n.key === key)?.id ?? key;
  const nodes: FlowNodeChange[] = [];
  for (const n of draft.nodes) {
    const kind = n.kind as FlowNodeUpsert["kind"];
    if (n.id === null) {
      nodes.push({
        ref: n.key,
        kind,
        name: n.name,
        config: n.config,
        position_x: n.x,
        position_y: n.y,
        ...(n.stage ? { stage: n.stage } : {})
      });
      continue;
    }
    const base = draft.base.find((b) => b.key === n.key);
    const unchanged = base && base.name === n.name && base.x === n.x && base.y === n.y;
    if (unchanged && sameValue(base.config, n.config)) continue;
    nodes.push({ id: n.id, kind, name: n.name, config: n.config, stage_id: n.stageId, position_x: n.x, position_y: n.y });
  }
  return {
    nodes,
    edges: draft.edges
      .filter((e) => e.id === null)
      .map((e) => ({ source: idOf(e.source), source_port: e.sourcePort, target: idOf(e.target), target_port: e.targetPort })),
    delete_node_ids: draft.deletedNodeIds,
    delete_edge_ids: draft.deletedEdgeIds
  };
};

export const isDirty = (draft: FlowDraft): boolean => {
  const c = toChanges(draft);
  return c.nodes.length + c.edges.length + c.delete_node_ids.length + c.delete_edge_ids.length > 0;
};

/**
 * A clean (or missing) draft is replaced by the read. A dirty one takes the read's statuses and, per saved node, every field
 * the admin has not touched, and the read becomes its new base, so Save sends only what the admin changed. A name or config the
 * admin edited stays, flagged `serverChanged` when the server changed that field too (the edit then replaces the server's).
 */
export const refreshDraft = (draft: FlowDraft | null, read: FlowRead): FlowDraft => {
  if (!draft || !isDirty(draft)) return draftFromRead(read);
  const fresh = new Map(read.nodes.map((n) => [n.id, readNode(n)]));
  const base = new Map(draft.base.map((b) => [b.key, b]));
  const nodes = draft.nodes.map((n): DraftNode => {
    const server = n.id === null ? undefined : fresh.get(n.id);
    const old = base.get(n.key);
    if (!server || !old) return n;
    const editedConfig = !sameValue(n.config, old.config);
    const editedName = n.name !== old.name;
    const conflict =
      (editedConfig && !sameValue(server.config, old.config) && !sameValue(server.config, n.config)) ||
      (editedName && server.name !== old.name && server.name !== n.name);
    return {
      ...n,
      status: server.status,
      stageId: server.stageId,
      config: editedConfig ? n.config : server.config,
      name: editedName ? n.name : server.name,
      x: n.x === old.x ? server.x : n.x,
      y: n.y === old.y ? server.y : n.y,
      serverChanged: n.serverChanged === true || conflict
    };
  });
  return { ...draft, nodes, base: draft.base.map((b) => (b.id === null ? b : (fresh.get(b.id) ?? b))) };
};

/** Unsaved, pure, or a lifecycle node that has not left `draft`. */
export const canDelete = (node: DraftNode): boolean => node.id === null || !isLifecycle(node.kind) || node.status === "draft";

/** The saved registration, formation and stage nodes this draft deletes: their data goes with them, so Save asks first. */
export const deletedLifecycleNodes = (draft: FlowDraft): DraftNode[] =>
  draft.base.filter((n) => n.id !== null && draft.deletedNodeIds.includes(n.id) && isLifecycle(n.kind));

const push = <K>(map: Map<K, FlowIssueRead[]>, key: K, issue: FlowIssueRead) => map.set(key, [...(map.get(key) ?? []), issue]);

export const keyedValidation = (
  draft: FlowDraft,
  issues: FlowIssueRead[],
  ports: { node_id: number; ports: FlowPortRead[] }[],
  refIds: Record<string, number> = {},
  newEdgeIds: number[] = []
): KeyedValidation => {
  const nodeKeys = new Set(draft.nodes.map((n) => n.key));
  const newEdges = draft.edges.filter((e) => e.id === null);
  const edgeKeys = new Set(draft.edges.map((e) => e.key));
  const nodeKey = (id: number): string | undefined => {
    const key = id > 0 ? String(id) : Object.keys(refIds).find((ref) => refIds[ref] === id);
    return key !== undefined && nodeKeys.has(key) ? key : undefined;
  };
  const edgeKey = (id: number): string | undefined => {
    const key = id > 0 ? `e${id}` : newEdges[newEdgeIds.indexOf(id)]?.key;
    return key !== undefined && edgeKeys.has(key) ? key : undefined;
  };

  const out: KeyedValidation = { nodeIssues: new Map(), edgeIssues: new Map(), general: [], ports: new Map() };
  for (const issue of issues) {
    const ek = issue.edge_id === null ? undefined : edgeKey(issue.edge_id);
    const nk = issue.node_id === null ? undefined : nodeKey(issue.node_id);
    if (ek !== undefined) push(out.edgeIssues, ek, issue);
    else if (nk !== undefined) push(out.nodeIssues, nk, issue);
    else out.general.push(issue);
  }
  for (const p of ports) {
    const key = nodeKey(p.node_id);
    if (key !== undefined) out.ports.set(key, p.ports);
  }
  return out;
};
