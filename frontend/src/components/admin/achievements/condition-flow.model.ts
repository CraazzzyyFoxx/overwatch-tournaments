/**
 * Condition-DSL ↔ flow-graph conversion, layout and labelling.
 *
 * Everything here is pure: no React, no `@xyflow/react` runtime import (the
 * `Node`/`Edge` types are type-only, so this module stays out of the editor's
 * lazily loaded chunk boundary and can be unit-tested without a canvas).
 */
import type { Edge, Node } from "@xyflow/react";

// ─── Constants ───────────────────────────────────────────────────────────────

export const OPERATORS = ["==", "!=", ">=", ">", "<=", "<"];
export const STATS = [
  "Eliminations", "FinalBlows", "Deaths", "AllDamageDealt", "HeroDamageDealt",
  "HealingDealt", "DamageTaken", "DamageBlocked", "EnvironmentalKills",
  "EnvironmentalDeaths", "ScopedCriticalHitKills", "SoloKills", "CriticalHits",
  "HeroTimePlayed", "UltimatesEarned", "Performance", "KD", "KDA",
];

/**
 * Acronyms and shorthands a mechanical kebab→Title would mangle. Everything
 * else derives from the node name itself, so a node added on the backend shows
 * up here without an edit.
 */
const LABEL_TOKENS: Record<string, string> = {
  kd: "K/D",
  mvp: "MVP",
  otp: "OTP",
  div: "division",
};

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

// ─── Types ───────────────────────────────────────────────────────────────────

export type TreeNode = Record<string, unknown>;

export interface FlatNode {
  id: string;
  type: "logical" | "leaf";
  logicalOp?: string;
  conditionType?: string;
  params?: Record<string, unknown>;
  parentId?: string;
}

export interface SidebarItem {
  type: "logical" | "leaf";
  label: string;
  logicalOp?: string;
  conditionType?: string;
  /** Logical operators only — leaves all share the success tone. */
  color?: string;
}

// ─── Labels ──────────────────────────────────────────────────────────────────

export function conditionLabel(name: string | undefined): string {
  if (!name) return "condition";
  const words = name.split("_").map((word) => LABEL_TOKENS[word] ?? word);
  const sentence = words.join(" ");
  return sentence.charAt(0).toUpperCase() + sentence.slice(1);
}

export function formatParamsSummary(type: string, params: Record<string, unknown>): string {
  const parts: string[] = [];
  if (params.stat) parts.push(String(params.stat));
  if (params.field && type !== "distinct_count") parts.push(String(params.field));
  if (params.op) parts.push(`${params.op} ${params.value ?? ""}`);
  if (params.direction) parts.push(`${params.direction} >= ${params.min_shift}`);
  if (params.hero_slug) parts.push(`hero: ${params.hero_slug}`);
  if (params.metric) parts.push(`${params.metric}, streak >= ${params.min_streak}`);
  if (params.order) parts.push(`${params.order} ${params.limit ?? ""}`);
  if (type === "match_mvp_check") {
    parts.push(`${params.stat ?? "Performance"} top ${params.top_n ?? 3}, team in top ${params.op ?? "=="} ${params.value ?? 0}`);
  }
  if (type === "tournament_format") {
    const fmtLabels: Record<string, string> = { double_elim: "Double elim", single_elim: "Single elim", round_robin: "Round robin", has_bracket: "Any bracket" };
    parts.push(fmtLabels[(params.format as string) ?? "double_elim"] ?? String(params.format));
  }
  if (type === "bracket_path") {
    const path = params.played_upper_bracket === true ? "upper only" : "lower bracket";
    const lb = params.min_lower_bracket_wins ? `, LB wins >= ${params.min_lower_bracket_wins}` : "";
    const lr = (params.lost_in_round as { op?: string; value?: number })?.op
      ? `, lost round ${(params.lost_in_round as { op?: string }).op} ${(params.lost_in_round as { value?: number }).value}`
      : "";
    parts.push(`${path}${lb}${lr}`);
  }
  if (type === "tournament_type") {
    parts.push(params.is_league === null || params.is_league === undefined ? "any" : `league: ${params.is_league}`);
  }
  if (type === "is_newcomer" && params.op) {
    parts.push(`newcomer count ${params.op} ${params.value}`);
  }
  if (params.field && type === "distinct_count") parts.push(`${params.field} ${params.op} ${params.value}`);
  if (type === "player_role") parts.push(`role: ${params.role ?? ""}`);
  if (type === "player_div") parts.push(`div ${params.op ?? "=="} ${params.value ?? ""}`);
  if (params.fields && type === "stable_streak") {
    const fields = params.fields as string[];
    parts.push(`[${fields.join(", ")}] streak >= ${params.min_streak ?? 2}`);
  }
  return parts.join(", ");
}

// ─── Tree ↔ flat conversion ─────────────────────────────────────────────────

export function getNextNodeId(nodes: FlatNode[], offset = 1): string {
  const maxId = nodes.reduce((max, node) => {
    const num = parseInt(node.id.replace("node_", ""), 10);
    return isNaN(num) ? max : Math.max(max, num);
  }, 0);
  return `node_${maxId + offset}`;
}

export function treeToFlat(tree: TreeNode, parentId?: string, counter = { id: 0 }): FlatNode[] {
  const nextId = () => `node_${++counter.id}`;

  // Empty tree — create a single root AND node
  if (!tree || Object.keys(tree).length === 0) {
    const id = nextId();
    return [{ id, type: "logical", logicalOp: "AND", parentId }];
  }

  const nodes: FlatNode[] = [];

  for (const op of ["AND", "OR", "NOT"] as const) {
    if (op in tree) {
      const id = nextId();
      nodes.push({ id, type: "logical", logicalOp: op, parentId });
      const children = op === "NOT" ? [tree[op] as TreeNode] : (tree[op] as TreeNode[]);
      for (const child of children) {
        nodes.push(...treeToFlat(child, id, counter));
      }
      return nodes;
    }
  }

  // Leaf
  const id = nextId();
  nodes.push({
    id,
    type: "leaf",
    conditionType: (tree.type as string) || "match_win",
    params: (tree.params as Record<string, unknown>) || {},
    parentId,
  });
  return nodes;
}

export function flatToTree(nodes: FlatNode[], rootId: string): TreeNode {
  const node = nodes.find((n) => n.id === rootId);
  if (!node) return { type: "match_win" };

  if (node.type === "logical") {
    const children = nodes.filter((n) => n.parentId === rootId);
    const childTrees = children.map((c) => flatToTree(nodes, c.id));

    if (node.logicalOp === "NOT") {
      return { NOT: childTrees[0] || { type: "match_win" } };
    }
    return { [node.logicalOp!]: childTrees };
  }

  // Leaf
  const result: TreeNode = { type: node.conditionType };
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
function paletteNode(item: SidebarItem, id: string, parentId?: string): FlatNode {
  return item.type === "logical"
    ? { id, type: "logical", logicalOp: item.logicalOp ?? "AND", parentId }
    : { id, type: "leaf", conditionType: item.conditionType ?? "match_win", params: {}, parentId };
}

/**
 * Appends a palette item to the root group. A bare leaf root cannot take
 * children, so it gets wrapped in an AND first and both nodes hang off the new
 * root.
 */
export function appendPaletteItem(flatNodes: FlatNode[], item: SidebarItem): FlatNode[] {
  const root = flatNodes.find((n) => !n.parentId);
  if (!root) return flatNodes;

  if (root.type === "leaf") {
    const newRootId = getNextNodeId(flatNodes, 1);
    const newChildId = getNextNodeId(flatNodes, 2);

    const newRoot: FlatNode = { id: newRootId, type: "logical", logicalOp: "AND" };
    const updatedRoot = { ...root, parentId: newRootId };
    const updated = flatNodes.map((n) => (n.id === root.id ? updatedRoot : n));
    updated.unshift(newRoot);
    updated.push(paletteNode(item, newChildId, newRootId));
    return updated;
  }

  return [...flatNodes, paletteNode(item, getNextNodeId(flatNodes), root.id)];
}

/** A new child of the given type, appended to `parentId`. */
export function appendChild(flatNodes: FlatNode[], parentId: string, childType: string): FlatNode[] {
  const newId = getNextNodeId(flatNodes);
  const newNode: FlatNode = childType === "logical"
    ? { id: newId, type: "logical", logicalOp: "AND", parentId }
    : { id: newId, type: "leaf", conditionType: "match_win", params: {}, parentId };
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
          stroke: LOGICAL_COLORS[flatNodes.find((n) => n.id === fn.parentId)?.logicalOp ?? "AND"] ?? HANDLE_COLOR,
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

// ─── Palette ─────────────────────────────────────────────────────────────────

export const SIDEBAR_GROUPS: { label: string; items: SidebarItem[] }[] = [
  {
    label: "Logic",
    items: [
      { type: "logical", logicalOp: "AND", label: "AND", color: LOGICAL_COLORS.AND },
      { type: "logical", logicalOp: "OR", label: "OR", color: LOGICAL_COLORS.OR },
      { type: "logical", logicalOp: "NOT", label: "NOT", color: LOGICAL_COLORS.NOT },
    ],
  },
  {
    label: "Match",
    items: [
      { type: "leaf", conditionType: "stat_threshold", label: "Stat threshold" },
      { type: "leaf", conditionType: "match_criteria", label: "Match criteria" },
      { type: "leaf", conditionType: "match_win", label: "Match win" },
      { type: "leaf", conditionType: "hero_stat", label: "Hero stat" },
      { type: "leaf", conditionType: "match_mvp_check", label: "MVP check" },
    ],
  },
  {
    label: "Tournament",
    items: [
      { type: "leaf", conditionType: "standing_position", label: "Position" },
      { type: "leaf", conditionType: "standing_record", label: "Record" },
      { type: "leaf", conditionType: "div_change", label: "Division change" },
      { type: "leaf", conditionType: "div_level", label: "Division level" },
      { type: "leaf", conditionType: "is_captain", label: "Is captain" },
      { type: "leaf", conditionType: "is_newcomer", label: "Is newcomer" },
      { type: "leaf", conditionType: "tournament_type", label: "Tournament type" },
      { type: "leaf", conditionType: "hero_kd_best", label: "Hero K/D best" },
      { type: "leaf", conditionType: "team_players_match", label: "Team players" },
      { type: "leaf", conditionType: "captain_property", label: "Captain property" },
      { type: "leaf", conditionType: "encounter_score", label: "Encounter score" },
      { type: "leaf", conditionType: "encounter_revenge", label: "Encounter revenge" },
      { type: "leaf", conditionType: "bracket_path", label: "Bracket path" },
      { type: "leaf", conditionType: "tournament_format", label: "Format" },
    ],
  },
  {
    label: "Global",
    items: [
      { type: "leaf", conditionType: "global_stat_sum", label: "Global stat sum" },
      { type: "leaf", conditionType: "tournament_count", label: "Tournament count" },
      { type: "leaf", conditionType: "global_winrate", label: "Global winrate" },
      { type: "leaf", conditionType: "distinct_count", label: "Distinct count" },
      { type: "leaf", conditionType: "consecutive", label: "Consecutive" },
      { type: "leaf", conditionType: "stable_streak", label: "Stable streak" },
    ],
  },
];
