"use client";

import { useCallback, useMemo, useState, type ReactNode } from "react";

import { GraphCanvas } from "@/components/graph-canvas/GraphCanvas";

import { RuleTreeOutline } from "./RuleTreeOutline";
import {
  LeafNode,
  LogicalNode,
  RuleBuilderContext,
  type RuleBuilderConfig,
  type RuleBuilderEditLabels,
  type RuleBuilderViewLabels,
  type RuleLeafFieldsProps,
  type RuleLeafOption,
} from "./RuleNodes";
import {
  LEAF_COLOR,
  accentOf,
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

interface RuleBuilderCommonProps {
  value: TreeNode;
  /** The leaf a fresh node and an unnamed stored one resolve to. */
  defaultLeafType: string;
  labelForLeaf: (type: string | undefined) => string;
  /** One-line read-only summary, for the outline and read-only nodes. */
  summarizeLeaf: (type: string, params: Record<string, unknown>) => string;
  /** The canvas' height utility, e.g. `h-125`. */
  heightClass: string;
}

/**
 * Editing and viewing are two different components behind one name: a viewer
 * has no palette, no type picker and no parameter form, so requiring them
 * would mean every read-only call site inventing dummies.
 */
export type RuleBuilderProps = RuleBuilderCommonProps &
  (
    | {
        readOnly: true;
        onChange?: never;
        leafOptions?: never;
        palette?: never;
        renderLeafFields?: never;
        labels: RuleBuilderViewLabels;
      }
    | {
        readOnly?: boolean;
        onChange?: (tree: TreeNode) => void;
        /** Leaf types the type `<Select>` offers, in menu order. */
        leafOptions: RuleLeafOption[];
        palette: RulePaletteGroup[];
        /** One leaf's parameter form — the only engine-specific part of a node. */
        renderLeafFields: (props: RuleLeafFieldsProps) => ReactNode;
        labels: RuleBuilderEditLabels;
      }
  );

// Module-level: xyflow remounts every node when `nodeTypes` changes identity.
const nodeTypes = { logicalNode: LogicalNode, leafNode: LeafNode };

/** A palette row's key: what it adds, which is unique even where two groups offer the same leaf. */
const paletteKey = (item: RulePaletteItem) => `${item.type}:${item.logicalOp ?? item.leafType ?? ""}`;

/**
 * The shared condition-tree canvas: the shared graph canvas over a flat
 * parent-pointer graph laid out as a tree, plus a screen-reader outline.
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

  return (
    <RuleBuilderContext.Provider value={config}>
      <RuleBuilderInner {...props} />
    </RuleBuilderContext.Provider>
  );
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

  /**
   * Applies a pure edit to the flat tree and publishes the rebuilt DSL. Publishing happens here, in the edit's event:
   * a state updater runs while React renders this component, and `onChange` sets the parent's state.
   */
  const applyEdit = useCallback(
    (edit: (prev: FlatNode[]) => FlatNode[]) => {
      const updated = edit(flatNodes);
      setFlatNodes(updated);
      const root = updated.find((n) => !n.parentId);
      if (root && onChange) onChange(flatToTree(updated, root.id, defaultLeafType));
    },
    [flatNodes, onChange, defaultLeafType]
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

  // The laid-out nodes, each carrying its frame colour and the callbacks in `data`.
  const { nodes, edges } = useMemo(() => {
    const layout = layoutNodes(flatNodes);
    const byId = new Map(flatNodes.map((fn) => [fn.id, fn]));
    return {
      nodes: layout.nodes.map((n) => {
        const fn = byId.get(n.id);
        return fn
          ? {
              ...n,
              data: {
                ...fn,
                path: nodePaths[fn.id],
                accent: accentOf(fn),
                readOnly,
                onChangeOp: readOnly ? undefined : handleChangeOp,
                onChangeType: readOnly ? undefined : handleChangeType,
                onChangeParam: readOnly ? undefined : handleChangeParam,
                onAddChild: readOnly ? undefined : handleAddChild,
                onDelete: readOnly ? undefined : handleDelete,
              },
            }
          : n;
      }),
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

  // Every palette row (a click or a drop) lands in the root group, wherever it was dropped.
  const canvasPalette = useMemo(() => {
    if (readOnly || !palette) return undefined;
    const items = new Map(palette.flatMap((group) => group.items).map((item) => [paletteKey(item), item]));
    return {
      groups: palette.map((group) => ({
        label: group.label,
        items: group.items.map((item) => ({
          key: paletteKey(item),
          label: item.label,
          description: item.description,
          color: item.color ?? LEAF_COLOR,
        })),
      })),
      onAdd: (key: string) => {
        const item = items.get(key);
        if (item) applyEdit((prev) => appendPaletteItem(prev, item, defaultLeafType));
      },
    };
  }, [readOnly, palette, applyEdit, defaultLeafType]);

  // The outline is `sr-only`: inside the canvas it takes no room beside it and follows it into fullscreen.
  return (
    <GraphCanvas
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      readOnly={readOnly}
      heightClass={heightClass}
      palette={canvasPalette}
    >
      <RuleTreeOutline
        nodes={flatNodes}
        paths={nodePaths}
        title={labels.outlineTitle}
        describeGroup={labels.outlineGroup}
        labelForLeaf={labelForLeaf}
        summarizeLeaf={summarizeLeaf}
      />
    </GraphCanvas>
  );
}
