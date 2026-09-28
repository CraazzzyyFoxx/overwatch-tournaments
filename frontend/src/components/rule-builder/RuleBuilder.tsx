"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  Panel,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Maximize2, Minimize2 } from "lucide-react";

import { Button } from "@/components/ui/button";

import { RulePalette, RULE_NODE_MIME } from "./RulePalette";
import { RuleTreeOutline } from "./RuleTreeOutline";
import {
  LeafNode,
  LogicalNode,
  RuleBuilderContext,
  type RuleBuilderConfig,
  type RuleBuilderLabels,
  type RuleLeafFieldsProps,
  type RuleLeafOption,
} from "./RuleNodes";
import {
  LEAF_COLOR,
  LOGICAL_COLORS,
  appendChild,
  appendPaletteItem,
  buildNodePaths,
  flatToTree,
  layoutNodes,
  removeSubtree,
  treeToFlat,
  type FlatNode,
  type RulePaletteGroup,
  type RulePaletteItem,
  type TreeNode,
} from "./rule-tree";

export interface RuleBuilderProps {
  value: TreeNode;
  onChange?: (tree: TreeNode) => void;
  readOnly?: boolean;
  /** Leaf types the type `<Select>` offers, in menu order. */
  leafOptions: RuleLeafOption[];
  /** The leaf a fresh node and an unnamed stored one resolve to. */
  defaultLeafType: string;
  palette: RulePaletteGroup[];
  /** One leaf's parameter form — the only engine-specific part of a node. */
  renderLeafFields: (props: RuleLeafFieldsProps) => ReactNode;
  labelForLeaf: (type: string | undefined) => string;
  /** One-line read-only summary, for the outline and read-only nodes. */
  summarizeLeaf: (type: string, params: Record<string, unknown>) => string;
  labels: RuleBuilderLabels;
  /** Canvas height class; defaults to the editor/viewer heights. */
  heightClass?: string;
}

/**
 * The shared condition-tree canvas: React Flow over a flat parent-pointer
 * graph, a palette, and a screen-reader outline.
 *
 * Engine-agnostic by construction — the leaf registry, the palette and the
 * parameter form all arrive as props, so the achievement rule editor and the
 * pick-ban constructor are the same component with two registries.
 */
export function RuleBuilder(props: Readonly<RuleBuilderProps>) {
  const config = useMemo<RuleBuilderConfig>(
    () => ({
      leafOptions: props.leafOptions,
      defaultLeafType: props.defaultLeafType,
      labelForLeaf: props.labelForLeaf,
      summarizeLeaf: props.summarizeLeaf,
      renderLeafFields: props.renderLeafFields,
      labels: props.labels,
    }),
    [
      props.leafOptions,
      props.defaultLeafType,
      props.labelForLeaf,
      props.summarizeLeaf,
      props.renderLeafFields,
      props.labels,
    ]
  );

  const editor = props.readOnly ? (
    <RuleBuilderInner {...props} />
  ) : (
    <ReactFlowProvider>
      <RuleBuilderInner {...props} />
    </ReactFlowProvider>
  );
  return <RuleBuilderContext.Provider value={config}>{editor}</RuleBuilderContext.Provider>;
}

function RuleBuilderInner({
  value,
  onChange,
  readOnly = false,
  defaultLeafType,
  palette,
  labelForLeaf,
  summarizeLeaf,
  labels,
  heightClass,
}: Readonly<RuleBuilderProps>) {
  const [prevValue, setPrevValue] = useState(value);
  const [flatNodes, setFlatNodes] = useState<FlatNode[]>(() => treeToFlat(value, defaultLeafType));

  if (value !== prevValue) {
    setPrevValue(value);
    setFlatNodes(treeToFlat(value, defaultLeafType));
  }

  /** Applies a pure edit to the flat tree and publishes the rebuilt DSL. */
  const applyEdit = useCallback(
    (edit: (prev: FlatNode[]) => FlatNode[]) => {
      setFlatNodes((prev) => {
        const updated = edit(prev);
        const root = updated.find((n) => !n.parentId);
        if (root && onChange) onChange(flatToTree(updated, root.id, defaultLeafType));
        return updated;
      });
    },
    [onChange, defaultLeafType]
  );

  const handleChangeOp = useCallback((nodeId: string, op: string) => {
    applyEdit((prev) => prev.map((n) => (n.id === nodeId ? { ...n, logicalOp: op } : n)));
  }, [applyEdit]);

  const handleChangeType = useCallback((nodeId: string, type: string) => {
    applyEdit((prev) => prev.map((n) => (n.id === nodeId ? { ...n, leafType: type, params: {} } : n)));
  }, [applyEdit]);

  const handleChangeParam = useCallback((nodeId: string, key: string, val: unknown) => {
    applyEdit((prev) =>
      prev.map((n) => (n.id === nodeId ? { ...n, params: { ...(n.params ?? {}), [key]: val } } : n))
    );
  }, [applyEdit]);

  const handleAddChild = useCallback((parentId: string, childType: string) => {
    applyEdit((prev) => appendChild(prev, parentId, childType, defaultLeafType));
  }, [applyEdit, defaultLeafType]);

  const handleDelete = useCallback((nodeId: string) => {
    applyEdit((prev) => removeSubtree(prev, nodeId));
  }, [applyEdit]);

  const nodePaths = useMemo(() => buildNodePaths(flatNodes), [flatNodes]);

  // Build React Flow nodes/edges with callbacks injected into data
  const { nodes: flowNodes, edges: flowEdges } = useMemo(() => {
    const enriched = flatNodes.map((fn) => ({
      ...fn,
      path: nodePaths[fn.id],
      readOnly,
      onChangeOp: readOnly ? undefined : handleChangeOp,
      onChangeType: readOnly ? undefined : handleChangeType,
      onChangeParam: readOnly ? undefined : handleChangeParam,
      onAddChild: readOnly ? undefined : handleAddChild,
      onDelete: readOnly ? undefined : handleDelete,
    }));

    const layout = layoutNodes(flatNodes);

    return {
      nodes: layout.nodes.map((n) => ({
        ...n,
        data: enriched.find((fn) => fn.id === n.id) ?? n.data,
      })),
      edges: layout.edges,
    };
  }, [
    flatNodes,
    nodePaths,
    readOnly,
    handleChangeOp,
    handleChangeType,
    handleChangeParam,
    handleAddChild,
    handleDelete,
  ]);

  const [nodes, setNodes, onNodesChange] = useNodesState(flowNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(flowEdges);

  // Sync when flow layout changes
  useEffect(() => {
    setNodes(flowNodes);
    setEdges(flowEdges);
  }, [flowNodes, flowEdges, setNodes, setEdges]);

  const nodeTypes = useMemo(() => ({ logicalNode: LogicalNode, leafNode: LeafNode }), []);

  // ─── Adding nodes from the palette ────────────────────────────────────────

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);

  /** Appends a palette item to the root group. Shared by drop and click. */
  const addPaletteItem = useCallback(
    (item: RulePaletteItem) => {
      applyEdit((prev) => appendPaletteItem(prev, item, defaultLeafType));
    },
    [applyEdit, defaultLeafType]
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const raw = e.dataTransfer.getData(RULE_NODE_MIME);
      if (!raw) return;
      // Serialised by RulePalette a moment ago, so the shape is ours.
      addPaletteItem(JSON.parse(raw) as RulePaletteItem);
    },
    [addPaletteItem]
  );

  // ─── Fullscreen ──────────────────────────────────────────────────────────────

  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    if (!fullscreen) return;
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFullscreen(false);
    };
    document.addEventListener("keydown", handleEsc);
    return () => document.removeEventListener("keydown", handleEsc);
  }, [fullscreen]);

  // Lock body scroll when fullscreen
  useEffect(() => {
    if (fullscreen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [fullscreen]);

  // ─── Render ─────────────────────────────────────────────────────────────────

  const containerClass = fullscreen
    ? "fixed inset-0 z-50 bg-background flex"
    : `${heightClass ?? (readOnly ? "h-75" : "h-125")} w-full rounded-lg border bg-background flex`;

  return (
    <div className={containerClass}>
      <RuleTreeOutline
        nodes={flatNodes}
        paths={nodePaths}
        title={labels.outlineTitle}
        describeGroup={labels.outlineGroup}
        labelForLeaf={labelForLeaf}
        summarizeLeaf={summarizeLeaf}
      />
      {!readOnly && <RulePalette groups={palette} labels={labels} onAdd={addPaletteItem} />}
      <div className="flex-1 relative">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={readOnly ? undefined : onNodesChange}
          onEdgesChange={readOnly ? undefined : onEdgesChange}
          nodeTypes={nodeTypes}
          nodesDraggable={!readOnly}
          nodesConnectable={false}
          elementsSelectable={!readOnly}
          onDragOver={readOnly ? undefined : onDragOver}
          onDrop={readOnly ? undefined : onDrop}
          fitView
          fitViewOptions={{ padding: 0.3 }}
          minZoom={0.3}
          maxZoom={1.5}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={20} size={1} />
          <Controls showInteractive={false} />
          {!readOnly && (
            <MiniMap
              nodeColor={(node) => {
                if (node.type === "logicalNode") {
                  return LOGICAL_COLORS[(node.data as unknown as FlatNode).logicalOp ?? "AND"];
                }
                return LEAF_COLOR;
              }}
              maskColor="rgba(0,0,0,0.2)"
            />
          )}
          <Panel position="top-right">
            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8 bg-background/80 backdrop-blur"
              onClick={() => setFullscreen((v) => !v)}
              title={fullscreen ? labels.exitFullscreen : labels.fullscreen}
              aria-label={fullscreen ? labels.exitFullscreenLabel : labels.fullscreenLabel}
            >
              {fullscreen ? <Minimize2 className="h-4 w-4" aria-hidden /> : <Maximize2 className="h-4 w-4" aria-hidden />}
            </Button>
          </Panel>
        </ReactFlow>
      </div>
    </div>
  );
}
