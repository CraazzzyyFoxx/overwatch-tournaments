import { FINAL_STATUSES, NODE_TRANSITIONS } from "./lifecycle";

type LifecycleKind = keyof typeof NODE_TRANSITIONS;

/** The slice of a flow graph (`FlowRead` / `AdminFlowRead`) the planner reads. */
export type PathGraph = {
  nodes: readonly { id: number; kind: string; name: string; status: string }[];
  edges: readonly { source_node_id: number; target_node_id: number }[];
};

export type PathNode = PathGraph["nodes"][number];

/** One admin move: `POST /admin/flow-nodes/{node.id}/transition` with `{ status: to }`. */
export type FlowStep = { node: PathNode; from: string; to: string };

/** The status at which each lifecycle kind's output is final (`FINAL_STATUSES`, per kind). */
const FINAL_OF: Record<LifecycleKind, string> = { registration: "closed", formation: "completed", stage: "completed" };

const isLifecycle = (kind: string): kind is LifecycleKind => kind in NODE_TRANSITIONS;

/** The shortest `NODE_TRANSITIONS` path from `from` to `to` (exclusive of `from`); null when there is none. */
function route(kind: LifecycleKind, from: string, to: string): string[] | null {
  const previous = new Map<string, string>([[from, from]]);
  const queue = [from];
  while (queue.length > 0) {
    const current = queue.shift() as string;
    if (current === to) {
      const path: string[] = [];
      for (let at = to; at !== from; at = previous.get(at) as string) path.unshift(at);
      return path;
    }
    for (const next of NODE_TRANSITIONS[kind][current] ?? []) {
      if (!previous.has(next)) {
        previous.set(next, current);
        queue.push(next);
      }
    }
  }
  return null;
}

/**
 * The moves, in order, that bring `nodeId` to `target`, its inputs first. Mirrors the server's guard
 * (`FlowNodeService._assert_inputs_final`): a registration leaves `draft` freely; any other node only once every node
 * wired into it is final. A pure node (filter, merge…) is final once its own inputs are, so the walk goes through it.
 * Null when a move on the way is not in `NODE_TRANSITIONS` (e.g. a completed stage back to `ready`). The server still
 * decides: a tied cut or a downstream start refuses a move this plan offers.
 */
export function stepsTo(graph: PathGraph, nodeId: number, target: string): FlowStep[] | null {
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));
  const inputs = (id: number) =>
    graph.edges.filter((edge) => edge.target_node_id === id).map((edge) => byId.get(edge.source_node_id));
  const steps: FlowStep[] = [];
  const planned = new Set<number>();

  const finalize = (node: PathNode | undefined): boolean => {
    if (!node || FINAL_STATUSES.includes(node.status)) return true;
    if (isLifecycle(node.kind)) return bring(node, FINAL_OF[node.kind]);
    return inputs(node.id).every(finalize);
  };

  function bring(node: PathNode, to: string): boolean {
    if (planned.has(node.id)) return true;
    planned.add(node.id);
    if (!isLifecycle(node.kind)) return false;
    const path = route(node.kind, node.status, to);
    if (path === null) return false;
    if (path.length > 0 && node.status === "draft" && node.kind !== "registration" && !inputs(node.id).every(finalize)) {
      return false;
    }
    let from = node.status;
    for (const status of path) {
      steps.push({ node, from, to: status });
      from = status;
    }
    return true;
  }

  const node = byId.get(nodeId);
  return node && bring(node, target) ? steps : null;
}

/** The lifecycle nodes feeding `nodeId`, nearest last, walking through pure nodes; each once, in graph order. */
export function lifecycleAncestors(graph: PathGraph, nodeId: number): PathNode[] {
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));
  const seen = new Set<number>();
  const found: PathNode[] = [];
  const visit = (id: number) => {
    for (const edge of graph.edges.filter((current) => current.target_node_id === id)) {
      const source = byId.get(edge.source_node_id);
      if (!source || seen.has(source.id)) continue;
      seen.add(source.id);
      visit(source.id);
      if (isLifecycle(source.kind)) found.push(source);
    }
  };
  visit(nodeId);
  return found;
}

/** The first lifecycle node `nodeId` feeds (walking through pure nodes), or null. */
export function firstLifecycleSuccessor(graph: PathGraph, nodeId: number): PathNode | null {
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));
  const queue = [nodeId];
  const seen = new Set(queue);
  while (queue.length > 0) {
    const id = queue.shift() as number;
    const targets = graph.edges
      .filter((edge) => edge.source_node_id === id)
      .map((edge) => byId.get(edge.target_node_id))
      .filter((node): node is PathNode => node !== undefined && !seen.has(node.id))
      .sort((left, right) => left.id - right.id);
    const lifecycle = targets.find((node) => isLifecycle(node.kind));
    if (lifecycle) return lifecycle;
    for (const node of targets) {
      seen.add(node.id);
      queue.push(node.id);
    }
  }
  return null;
}
