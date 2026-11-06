import type { Edge, Node } from "@xyflow/react";

import { HANDLE_COLOR } from "@/components/rule-builder/rule-tree";
import type {
  FlowNodeKind,
  FlowNodeStatus as FlowNodeStatusValue,
  FlowPortRead,
  FlowRead,
  FlowUnit
} from "@/types/flow.types";

import { canDelete, type FlowDraft } from "./flowDraft";
import { UNIT_COLOR } from "./kinds";

/** The drag MIME of a palette row: the node kind being dropped. */
export const FLOW_NODE_MIME = "application/flow-node-kind";

export { HANDLE_COLOR };

export type FlowNodeData = {
  kind: FlowNodeKind;
  name: string;
  status: FlowNodeStatusValue | null;
  ports: FlowPortRead[];
  issueCount: number;
  readOnly: boolean;
  /** The server changed this node while the admin's edit of it was pending. */
  serverChanged: boolean;
};

/** Every node's ports as the server resolved them, in the shape `keyedValidation` takes. */
export const portsFromRead = (read: FlowRead): { node_id: number; ports: FlowPortRead[] }[] =>
  read.nodes.map((n) => ({ node_id: n.id, ports: n.ports }));

/** The draft as xyflow nodes and edges: handles from the resolved ports, edges coloured by the unit they carry. */
export function toCanvas(
  draft: FlowDraft,
  ports: Map<string, FlowPortRead[]>,
  issueCounts: Map<string, number>,
  edgeIssues: ReadonlySet<string>,
  readOnly: boolean
): { nodes: Node<FlowNodeData>[]; edges: Edge[] } {
  const nodes = draft.nodes.map((node): Node<FlowNodeData> => ({
    id: node.key,
    type: "flowNode",
    position: { x: node.x, y: node.y },
    deletable: canDelete(node) && !readOnly,
    data: {
      kind: node.kind,
      name: node.name,
      status: node.status,
      ports: ports.get(node.key) ?? [],
      issueCount: issueCounts.get(node.key) ?? 0,
      readOnly,
      serverChanged: node.serverChanged === true
    }
  }));
  const edges = draft.edges.map((edge): Edge => {
    const unit = ports.get(edge.source)?.find((p) => p.name === edge.sourcePort)?.unit as
      FlowUnit | null | undefined;
    const invalid = edgeIssues.has(edge.key);
    return {
      id: edge.key,
      source: edge.source,
      sourceHandle: edge.sourcePort,
      target: edge.target,
      targetHandle: edge.targetPort,
      style: { stroke: (unit && UNIT_COLOR[unit]) || HANDLE_COLOR },
      ...(invalid ? { className: "flow-edge-invalid", animated: true } : {})
    };
  });
  return { nodes, edges };
}
