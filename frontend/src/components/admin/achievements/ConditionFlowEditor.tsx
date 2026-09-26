"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
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
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { achievementQueryKeys } from "@/lib/achievements/query-keys";

import { ConditionPalette } from "./ConditionPalette";
import { ConditionTreeOutline } from "./ConditionTreeOutline";
import { ConditionTypesContext, LeafNode, LogicalNode } from "./ConditionNodes";
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
  type SidebarItem,
} from "./condition-flow.model";

interface ConditionFlowEditorProps {
  value: Record<string, unknown>;
  onChange?: (tree: Record<string, unknown>) => void;
  readOnly?: boolean;
}

export function ConditionFlowEditor(props: Readonly<ConditionFlowEditorProps>) {
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  // The registry only changes when the engine ships a new node, so it is cached
  // for the session rather than refetched per editor mount.
  const { data: conditionTypes } = useQuery({
    queryKey: achievementQueryKeys.conditionTypes(workspaceId),
    queryFn: () => adminService.getConditionTypes(workspaceId!),
    enabled: !!workspaceId,
    staleTime: Infinity
  });
  const registry = useMemo(() => conditionTypes ?? [], [conditionTypes]);

  const editor = props.readOnly ? (
    <ConditionFlowEditorInner {...props} />
  ) : (
    <ReactFlowProvider>
      <ConditionFlowEditorInner {...props} />
    </ReactFlowProvider>
  );
  return <ConditionTypesContext.Provider value={registry}>{editor}</ConditionTypesContext.Provider>;
}

function ConditionFlowEditorInner({ value, onChange, readOnly = false }: Readonly<ConditionFlowEditorProps>) {
  const [prevValue, setPrevValue] = useState(value);
  const [flatNodes, setFlatNodes] = useState<FlatNode[]>(() => {
    return treeToFlat(value);
  });

  if (value !== prevValue) {
    setPrevValue(value);
    setFlatNodes(treeToFlat(value));
  }

  /** Applies a pure edit to the flat tree and publishes the rebuilt DSL. */
  const applyEdit = useCallback(
    (edit: (prev: FlatNode[]) => FlatNode[]) => {
      setFlatNodes((prev) => {
        const updated = edit(prev);
        const root = updated.find((n) => !n.parentId);
        if (root && onChange) onChange(flatToTree(updated, root.id));
        return updated;
      });
    },
    [onChange],
  );

  const handleChangeOp = useCallback((nodeId: string, op: string) => {
    applyEdit((prev) => prev.map((n) => (n.id === nodeId ? { ...n, logicalOp: op } : n)));
  }, [applyEdit]);

  const handleChangeType = useCallback((nodeId: string, type: string) => {
    applyEdit((prev) => prev.map((n) => (n.id === nodeId ? { ...n, conditionType: type, params: {} } : n)));
  }, [applyEdit]);

  const handleChangeParam = useCallback((nodeId: string, key: string, val: unknown) => {
    applyEdit((prev) =>
      prev.map((n) => (n.id === nodeId ? { ...n, params: { ...(n.params ?? {}), [key]: val } } : n)),
    );
  }, [applyEdit]);

  const handleAddChild = useCallback((parentId: string, childType: string) => {
    applyEdit((prev) => appendChild(prev, parentId, childType));
  }, [applyEdit]);

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

    // Inject callbacks into node data
    return {
      nodes: layout.nodes.map((n) => ({
        ...n,
        data: enriched.find((fn) => fn.id === n.id) ?? n.data,
      })),
      edges: layout.edges,
    };
  }, [flatNodes, nodePaths, readOnly, handleChangeOp, handleChangeType, handleChangeParam, handleAddChild, handleDelete]);

  const [nodes, setNodes, onNodesChange] = useNodesState(flowNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(flowEdges);

  // Sync when flow layout changes
  useEffect(() => {
    setNodes(flowNodes);
    setEdges(flowEdges);
  }, [flowNodes, flowEdges, setNodes, setEdges]);

  const nodeTypes = useMemo(() => ({
    logicalNode: LogicalNode,
    leafNode: LeafNode,
  }), []);

  // ─── Adding nodes from the palette ────────────────────────────────────────

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);

  /** Appends a palette item to the root group. Shared by drop and click. */
  const addPaletteItem = useCallback(
    (item: SidebarItem) => {
      applyEdit((prev) => appendPaletteItem(prev, item));
    },
    [applyEdit],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const raw = e.dataTransfer.getData("application/condition-node");
      if (!raw) return;
      // Serialised by ConditionPalette a moment ago, so the shape is ours.
      addPaletteItem(JSON.parse(raw) as SidebarItem);
    },
    [addPaletteItem],
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
    : `${readOnly ? "h-75" : "h-125"} w-full rounded-lg border bg-background flex`;

  return (
    <div className={containerClass}>
      <ConditionTreeOutline nodes={flatNodes} paths={nodePaths} />
      {!readOnly && <ConditionPalette onAdd={addPaletteItem} />}
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
              title={fullscreen ? "Exit fullscreen (Esc)" : "Fullscreen"}
              aria-label={fullscreen ? "Exit fullscreen, or press Escape" : "Show the condition tree fullscreen"}
            >
              {fullscreen ? <Minimize2 className="h-4 w-4" aria-hidden /> : <Maximize2 className="h-4 w-4" aria-hidden />}
            </Button>
          </Panel>
        </ReactFlow>
      </div>
    </div>
  );
}
