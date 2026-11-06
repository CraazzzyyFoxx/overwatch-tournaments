"use client";

import type { CSSProperties, DragEvent } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
  type OnEdgesChange,
  type OnNodesChange
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { FLOW_NODE_MIME, type FlowNodeData } from "@/lib/flow/flowCanvas";
import type { FlowNodeKind } from "@/lib/flow/kinds";

import { FlowNodeCard } from "./FlowNodeCard";

/** xyflow chrome repainted in the app's shadcn tokens (as the rule builder does). */
const XY_THEME = {
  "--xy-background-color": "transparent",
  "--xy-background-pattern-color": "hsl(var(--muted-foreground) / 0.22)",
  "--xy-edge-stroke": "hsl(var(--muted-foreground) / 0.55)",
  "--xy-controls-box-shadow": "none",
  "--xy-controls-button-background-color": "hsl(var(--card))",
  "--xy-controls-button-background-color-hover": "hsl(var(--accent))",
  "--xy-controls-button-color": "hsl(var(--muted-foreground))",
  "--xy-controls-button-color-hover": "hsl(var(--foreground))",
  "--xy-controls-button-border-color": "hsl(var(--border))",
  "--xy-minimap-background-color": "hsl(var(--card))"
} as CSSProperties;

const nodeTypes = { flowNode: FlowNodeCard };

type FlowCanvasProps = {
  nodes: Node<FlowNodeData>[];
  edges: Edge[];
  readOnly: boolean;
  onNodesChange?: OnNodesChange<Node<FlowNodeData>>;
  onEdgesChange?: OnEdgesChange;
  onConnect?: (connection: Connection) => void;
  onNodeClick?: (key: string) => void;
  /** A palette row dropped on the canvas, at a flow-space position. */
  onDropKind?: (kind: FlowNodeKind, position: { x: number; y: number }) => void;
  /** The canvas' height utility, e.g. `h-[70vh]`. */
  heightClass: string;
};

function Canvas({
  nodes,
  edges,
  readOnly,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onNodeClick,
  onDropKind,
  heightClass
}: Readonly<FlowCanvasProps>) {
  const { screenToFlowPosition } = useReactFlow();

  const onDragOver = (e: DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    const kind = e.dataTransfer.getData(FLOW_NODE_MIME);
    if (kind)
      onDropKind?.(kind as FlowNodeKind, screenToFlowPosition({ x: e.clientX, y: e.clientY }));
  };

  return (
    <div
      className={`${heightClass} w-full rounded-lg border bg-background [&_.flow-edge-invalid_.react-flow__edge-path]:stroke-[color:var(--aqt-rose)]!`}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={readOnly ? undefined : onNodesChange}
        onEdgesChange={readOnly ? undefined : onEdgesChange}
        onConnect={readOnly ? undefined : onConnect}
        onNodeClick={onNodeClick ? (_event, node) => onNodeClick(node.id) : undefined}
        onDragOver={readOnly ? undefined : onDragOver}
        onDrop={readOnly ? undefined : onDrop}
        nodesConnectable={!readOnly}
        nodesDraggable={!readOnly}
        elementsSelectable={!readOnly}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        minZoom={0.3}
        maxZoom={1.5}
        proOptions={{ hideAttribution: true }}
        colorMode="dark"
        style={XY_THEME}
      >
        <Background gap={20} size={1} />
        <Controls showInteractive={false} />
        {readOnly ? null : <MiniMap maskColor="rgba(0,0,0,0.2)" />}
      </ReactFlow>
    </div>
  );
}

/** The flow graph on an xyflow canvas: editable with handlers, read-only without. Import it through `next/dynamic` in client-only screens. */
export function FlowCanvas(props: Readonly<FlowCanvasProps>) {
  return (
    <ReactFlowProvider>
      <Canvas {...props} />
    </ReactFlowProvider>
  );
}
