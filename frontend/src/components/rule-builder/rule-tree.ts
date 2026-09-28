/**
 * Condition-tree ↔ flow-graph conversion, layout and editing operations.
 *
 * The grammar is shared by two engines — achievement `condition_tree` and
 * pick-ban `Condition` (§2 of the pick-ban constructor plan): `{}` is "always
 * true", `AND`/`OR` take a list, `NOT` takes one child, and anything else is a
 * leaf `{type, params}`. Nothing here knows which leaves exist; the caller
 * brings the registry.
 *
 * Everything is pure: no React, no `@xyflow/react` runtime import (the
 * `Node`/`Edge` types are type-only, so this module stays out of the editor's
 * lazily loaded chunk boundary and can be unit-tested without a canvas).
 */
import type { Edge, Node } from "@xyflow/react";

// ─── Constants ───────────────────────────────────────────────────────────────

/**
 * React Flow paints edge strokes, minimap swatches and node borders straight
 * onto a canvas that Tailwind classes cannot reach, so the operator identities
 * resolve the tone tokens through `hsl(var(--…))` rather than hard-coding the
 * palette. Inline styles also outrank React Flow's own stylesheet, which is
 * why none of these need an `!important` class.
 */
export const LOGICAL_COLORS: Record<string, string> = {
  AND: "hsl(var(--info))",
  OR: "hsl(var(--warning))",
  NOT: "hsl(var(--danger))",
};

/** Leaf conditions are the satisfied/valid end of the tree → success tone. */
export const LEAF_COLOR = "hsl(var(--success))";
export const HANDLE_COLOR = "hsl(var(--muted-foreground))";

export const LOGICAL_OPS = ["AND", "OR", "NOT"] as const;

// ─── Types ───────────────────────────────────────────────────────────────────

/** One node of the DSL, as stored. */
export type TreeNode = Record<string, unknown>;

export interface FlatNode {
  id: string;
  type: "logical" | "leaf";
  logicalOp?: string;
  /** Registered leaf type, e.g. `stat_threshold` or `map_index`. */
  leafType?: string;
  params?: Record<string, unknown>;
  parentId?: string;
}

/** One row of the palette: a logical group, or a leaf of a known type. */
export interface RulePaletteItem {
  type: "logical" | "leaf";
  label: string;
  logicalOp?: string;
  /** Required for `type: "leaf"`. */
  leafType?: string;
  /** Logical operators only — leaves all share the success tone. */
  color?: string;
  description?: string;
}

export interface RulePaletteGroup {
  label: string;
  items: RulePaletteItem[];
}

// ─── Tree ↔ flat conversion ─────────────────────────────────────────────────

export function getNextNodeId(nodes: FlatNode[], offset = 1): string {
  const maxId = nodes.reduce((max, node) => {
    const num = parseInt(node.id.replace("node_", ""), 10);
    return isNaN(num) ? max : Math.max(max, num);
  }, 0);
  return `node_${maxId + offset}`;
}

/**
 * The DSL tree as a flat parent-pointer list.
 *
 * `defaultLeafType` fills in a leaf the stored tree does not name — an empty
 * object inside a group, or a malformed import. It is the caller's registry
 * that decides what a safe "anything" leaf is, so there is no fallback here.
 */
export function treeToFlat(
  tree: TreeNode,
  defaultLeafType: string,
  parentId?: string,
  counter = { id: 0 }
): FlatNode[] {
  const nextId = () => `node_${++counter.id}`;

  // Empty tree — create a single root AND node
  if (!tree || Object.keys(tree).length === 0) {
    const id = nextId();
    return [{ id, type: "logical", logicalOp: "AND", parentId }];
  }

  const nodes: FlatNode[] = [];

  for (const op of LOGICAL_OPS) {
    if (op in tree) {
      const id = nextId();
      nodes.push({ id, type: "logical", logicalOp: op, parentId });
      const children = op === "NOT" ? [tree[op] as TreeNode] : (tree[op] as TreeNode[]);
      for (const child of children ?? []) {
        nodes.push(...treeToFlat(child, defaultLeafType, id, counter));
      }
      return nodes;
    }
  }

  // Leaf
  const id = nextId();
  nodes.push({
    id,
    type: "leaf",
    leafType: (tree.type as string) || defaultLeafType,
    params: (tree.params as Record<string, unknown>) || {},
    parentId,
  });
  return nodes;
}

export function flatToTree(nodes: FlatNode[], rootId: string, defaultLeafType: string): TreeNode {
  const node = nodes.find((n) => n.id === rootId);
  if (!node) return { type: defaultLeafType };

  if (node.type === "logical") {
    const children = nodes.filter((n) => n.parentId === rootId);
    const childTrees = children.map((c) => flatToTree(nodes, c.id, defaultLeafType));

    if (node.logicalOp === "NOT") {
      return { NOT: childTrees[0] || { type: defaultLeafType } };
    }
    return { [node.logicalOp!]: childTrees };
  }

  // Leaf
  const result: TreeNode = { type: node.leafType };
  if (node.params && Object.keys(node.params).length > 0) {
    result.params = node.params;
  }
  return result;
}

/**
 * Positional path per node ("1.2.3"), used as the human handle for every
 * control inside a node. React Flow renders the tree as an absolutely
 * positioned flat list, so without a path an assistive-tech user meets thirty
 * identically named "Operator" selects with no way to tell them apart.
 */
export function buildNodePaths(nodes: FlatNode[]): Record<string, string> {
  const paths: Record<string, string> = {};

  const walk = (nodeId: string, path: string) => {
    paths[nodeId] = path;
    nodes
      .filter((child) => child.parentId === nodeId)
      .forEach((child, index) => walk(child.id, `${path}.${index + 1}`));
  };

  const root = nodes.find((node) => !node.parentId);
  if (root) {
    walk(root.id, "1");
  }
  return paths;
}

// ─── Editing operations ──────────────────────────────────────────────────────

/** A palette item as a fresh flat node parented to `parentId`. */
function paletteNode(
  item: RulePaletteItem,
  id: string,
  defaultLeafType: string,
  parentId?: string
): FlatNode {
  return item.type === "logical"
    ? { id, type: "logical", logicalOp: item.logicalOp ?? "AND", parentId }
    : { id, type: "leaf", leafType: item.leafType ?? defaultLeafType, params: {}, parentId };
}

/**
 * Appends a palette item to the root group. A bare leaf root cannot take
 * children, so it gets wrapped in an AND first and both nodes hang off the new
 * root.
 */
export function appendPaletteItem(
  flatNodes: FlatNode[],
  item: RulePaletteItem,
  defaultLeafType: string
): FlatNode[] {
  const root = flatNodes.find((n) => !n.parentId);
  if (!root) return flatNodes;

  if (root.type === "leaf") {
    const newRootId = getNextNodeId(flatNodes, 1);
    const newChildId = getNextNodeId(flatNodes, 2);

    const newRoot: FlatNode = { id: newRootId, type: "logical", logicalOp: "AND" };
    const updatedRoot = { ...root, parentId: newRootId };
    const updated = flatNodes.map((n) => (n.id === root.id ? updatedRoot : n));
    updated.unshift(newRoot);
    updated.push(paletteNode(item, newChildId, defaultLeafType, newRootId));
    return updated;
  }

  return [...flatNodes, paletteNode(item, getNextNodeId(flatNodes), defaultLeafType, root.id)];
}

/** A new child of the given type, appended to `parentId`. */
export function appendChild(
  flatNodes: FlatNode[],
  parentId: string,
  childType: string,
  defaultLeafType: string
): FlatNode[] {
  const newId = getNextNodeId(flatNodes);
  const newNode: FlatNode =
    childType === "logical"
      ? { id: newId, type: "logical", logicalOp: "AND", parentId }
      : { id: newId, type: "leaf", leafType: defaultLeafType, params: {}, parentId };
  return [...flatNodes, newNode];
}

/** Removes a node and every descendant hanging off it. */
export function removeSubtree(flatNodes: FlatNode[], nodeId: string): FlatNode[] {
  const toRemove = new Set<string>();
  const collect = (id: string) => {
    toRemove.add(id);
    flatNodes.filter((n) => n.parentId === id).forEach((n) => collect(n.id));
  };
  collect(nodeId);
  return flatNodes.filter((n) => !toRemove.has(n.id));
}

// ─── Layout ──────────────────────────────────────────────────────────────────

export function layoutNodes(flatNodes: FlatNode[]): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  const childrenMap: Record<string, FlatNode[]> = {};
  let root: FlatNode | undefined;

  for (const fn of flatNodes) {
    if (!fn.parentId) {
      root = fn;
    } else {
      (childrenMap[fn.parentId] ??= []).push(fn);
    }
  }

  if (!root) return { nodes, edges };

  const NODE_WIDTH = 280;
  const NODE_HEIGHT_LOGICAL = 60;
  const NODE_HEIGHT_LEAF = 160;
  const H_GAP = 60;
  const V_GAP = 30;

  // Calculate subtree sizes for layout
  function subtreeHeight(nodeId: string): number {
    const children = childrenMap[nodeId] ?? [];
    if (children.length === 0) {
      const fn = flatNodes.find((n) => n.id === nodeId);
      return fn?.type === "leaf" ? NODE_HEIGHT_LEAF : NODE_HEIGHT_LOGICAL;
    }
    return children.reduce((sum, c) => sum + subtreeHeight(c.id) + V_GAP, -V_GAP);
  }

  function placeNode(fn: FlatNode, x: number, y: number) {
    const isLogical = fn.type === "logical";
    const height = isLogical ? NODE_HEIGHT_LOGICAL : NODE_HEIGHT_LEAF;

    nodes.push({
      id: fn.id,
      type: isLogical ? "logicalNode" : "leafNode",
      position: { x, y },
      data: { ...fn },
      style: { width: NODE_WIDTH },
    });

    if (fn.parentId) {
      edges.push({
        id: `${fn.parentId}-${fn.id}`,
        source: fn.parentId,
        target: fn.id,
        style: {
          stroke:
            LOGICAL_COLORS[flatNodes.find((n) => n.id === fn.parentId)?.logicalOp ?? "AND"] ??
            HANDLE_COLOR,
          strokeWidth: 2,
        },
        animated: true,
      });
    }

    const children = childrenMap[fn.id] ?? [];
    if (children.length > 0) {
      const totalHeight = children.reduce((sum, c) => sum + subtreeHeight(c.id) + V_GAP, -V_GAP);
      let childY = y + height / 2 - totalHeight / 2;
      const childX = x + NODE_WIDTH + H_GAP;

      for (const child of children) {
        const childHeight = subtreeHeight(child.id);
        placeNode(child, childX, childY);
        childY += childHeight + V_GAP;
      }
    }
  }

  placeNode(root, 50, 50);
  return { nodes, edges };
}
