"use client";

import { createContext, useCallback, useContext, useEffect, useId, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  Handle,
  Position,
  type Node,
  type Edge,
  type NodeProps,
  Panel,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { FolderPlus, GripVertical, Maximize2, Minimize2, Plus, Search, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { ConditionTypeInfo } from "@/types/admin.types";

// ─── Constants ───────────────────────────────────────────────────────────────

const OPERATORS = ["==", "!=", ">=", ">", "<=", "<"];
const STATS = [
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

function conditionLabel(name: string | undefined): string {
  if (!name) return "condition";
  const words = name.split("_").map((word) => LABEL_TOKENS[word] ?? word);
  const sentence = words.join(" ");
  return sentence.charAt(0).toUpperCase() + sentence.slice(1);
}

/**
 * The node types the engine actually implements, served by
 * `achievements/rules/condition-types`. The editor used to keep its own copy,
 * which drifted eight nodes behind the backend; the palette now shows whatever
 * the engine registered, and `required`/`optional` come from the same place the
 * validator reads.
 */
const ConditionTypesContext = createContext<ConditionTypeInfo[]>([]);

/**
 * React Flow paints edge strokes, minimap swatches and node borders straight
 * onto a canvas that Tailwind classes cannot reach, so the operator identities
 * resolve the tone tokens through `hsl(var(--…))` rather than hard-coding the
 * palette. Inline styles also outrank React Flow's own stylesheet, which is
 * why none of these need an `!important` class.
 */
const LOGICAL_COLORS: Record<string, string> = {
  AND: "hsl(var(--info))",
  OR: "hsl(var(--warning))",
  NOT: "hsl(var(--danger))",
};

/** Leaf conditions are the satisfied/valid end of the tree → success tone. */
const LEAF_COLOR = "hsl(var(--success))";
const HANDLE_COLOR = "hsl(var(--muted-foreground))";

// ─── Types ───────────────────────────────────────────────────────────────────

interface ConditionFlowEditorProps {
  value: Record<string, unknown>;
  onChange?: (tree: Record<string, unknown>) => void;
  readOnly?: boolean;
}

type TreeNode = Record<string, unknown>;

interface FlatNode {
  id: string;
  type: "logical" | "leaf";
  logicalOp?: string;
  conditionType?: string;
  params?: Record<string, unknown>;
  parentId?: string;
}

// ─── Tree ↔ Flow conversion ─────────────────────────────────────────────────

function getNextNodeId(nodes: FlatNode[], offset = 1): string {
  const maxId = nodes.reduce((max, node) => {
    const num = parseInt(node.id.replace("node_", ""), 10);
    return isNaN(num) ? max : Math.max(max, num);
  }, 0);
  return `node_${maxId + offset}`;
}

function treeToFlat(tree: TreeNode, parentId?: string, counter = { id: 0 }): FlatNode[] {
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

function flatToTree(nodes: FlatNode[], rootId: string): TreeNode {
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
function buildNodePaths(nodes: FlatNode[]): Record<string, string> {
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

/**
 * Screen-reader outline of the tree.
 *
 * The canvas nesting exists only visually — React Flow lays every node out as
 * an absolutely positioned sibling and draws the parent/child relationship as
 * an SVG edge, which assistive tech cannot follow. This mirrors the same data
 * as a real nested list so the shape of the boolean expression is readable.
 * It is deliberately read-only: the editable controls stay on the canvas and
 * each one is named with its path so the two views line up.
 */
function TreeOutline({
  nodes,
  paths,
}: Readonly<{
  nodes: FlatNode[];
  paths: Record<string, string>;
}>) {
  const headingId = useId();

  const renderLevel = (parentId: string | undefined) => {
    const children = nodes.filter((node) => node.parentId === parentId);
    if (children.length === 0) {
      return null;
    }
    return (
      <ul>
        {children.map((node) => {
          const path = paths[node.id] ?? "?";
          let description: string;
          if (node.type === "logical") {
            description = `${path} ${node.logicalOp ?? "AND"} group`;
          } else {
            const label = conditionLabel(node.conditionType);
            const summary = formatParamsSummary(node.conditionType ?? "", node.params ?? {});
            description = summary ? `${path} ${label} · ${summary}` : `${path} ${label}`;
          }
          return (
            <li key={node.id}>
              {description}
              {renderLevel(node.id)}
            </li>
          );
        })}
      </ul>
    );
  };

  return (
    <div className="sr-only">
      <p id={headingId}>Condition tree outline</p>
      <div role="group" aria-labelledby={headingId}>
        {renderLevel(undefined)}
      </div>
    </div>
  );
}

function layoutNodes(flatNodes: FlatNode[]): { nodes: Node[]; edges: Edge[] } {
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

// ─── Custom Nodes ────────────────────────────────────────────────────────────

function LogicalNode({ data, id }: NodeProps) {
  const d = data as unknown as FlatNode & {
    path?: string;
    readOnly?: boolean;
    onChangeOp?: (id: string, op: string) => void;
    onAddChild?: (id: string, type: string) => void;
    onDelete?: (id: string) => void;
  };
  const op = d.logicalOp ?? "AND";
  const color = LOGICAL_COLORS[op];
  // Every control below is named by tree position, never by `id` — a node id
  // like "node_7" is a DOM detail and says nothing about which group is meant.
  const groupName = `group ${d.path ?? "1"}`;

  return (
    <div
      className="rounded-lg border-2 px-4 py-2 bg-card shadow-md"
      style={{ borderColor: color }}
    >
      <Handle type="target" position={Position.Left} aria-hidden style={{ background: HANDLE_COLOR }} />
      <div className="flex items-center gap-2">
        <span className="text-xs tabular-nums text-muted-foreground">{d.path ?? "1"}</span>
        {d.readOnly ? (
          <span className="text-xs font-bold px-2" style={{ color }}>{op}</span>
        ) : (
          <Select value={op} onValueChange={(val) => d.onChangeOp?.(id, val)}>
            <SelectTrigger
              className="w-20 h-8 text-xs font-bold"
              style={{ color }}
              aria-label={`Logic operator for ${groupName}`}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="AND">AND</SelectItem>
              <SelectItem value="OR">OR</SelectItem>
              <SelectItem value="NOT">NOT</SelectItem>
            </SelectContent>
          </Select>
        )}
        {!d.readOnly && (
          <>
            <div className="flex-1" />
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => d.onAddChild?.(id, "leaf")}
              title="Add condition"
              aria-label={`Add condition inside ${groupName}`}
            >
              <Plus className="h-3.5 w-3.5" aria-hidden />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => d.onAddChild?.(id, "logical")}
              title="Add group"
              aria-label={`Add nested group inside ${groupName}`}
            >
              <FolderPlus className="h-3.5 w-3.5" aria-hidden />
            </Button>
            {d.parentId && (
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                onClick={() => d.onDelete?.(id)}
                aria-label={`Delete ${groupName} and every condition inside it`}
              >
                <Trash2 className="h-3.5 w-3.5 text-destructive" aria-hidden />
              </Button>
            )}
          </>
        )}
      </div>
      <Handle type="source" position={Position.Right} aria-hidden style={{ background: HANDLE_COLOR }} />
    </div>
  );
}

function formatParamsSummary(type: string, params: Record<string, unknown>): string {
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

/** Stat select + operator/value row shared by `stat_threshold`/`global_stat_sum`
 * and `hero_stat` (which prefixes it with its own hero-slug input). */
function StatOpValueFields({
  params,
  setParam,
  controlName
}: Readonly<{
  params: Record<string, unknown>;
  setParam: (key: string, value: unknown) => void;
  controlName: (field: string) => string;
}>) {
  return (
    <>
      <Select value={(params.stat as string) ?? ""} onValueChange={(v) => setParam("stat", v)}>
        <SelectTrigger className="h-7 text-xs" aria-label={controlName("Stat")}><SelectValue placeholder="Stat…" /></SelectTrigger>
        <SelectContent>{STATS.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
      </Select>
      <div className="flex gap-1">
        <Select value={(params.op as string) ?? ">="} onValueChange={(v) => setParam("op", v)}>
          <SelectTrigger className="h-7 text-xs w-16" aria-label={controlName("Operator")}><SelectValue /></SelectTrigger>
          <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
        </Select>
        <NumberInput className="h-7 text-xs" aria-label={controlName("Threshold value")} value={(params.value as number) ?? 0} onValueChange={(next) => setParam("value", next ?? 0)} />
      </div>
    </>
  );
}

function LeafNode({ data, id }: NodeProps) {
  const d = data as unknown as FlatNode & {
    path?: string;
    readOnly?: boolean;
    onChangeType?: (id: string, type: string) => void;
    onChangeParam?: (id: string, key: string, value: unknown) => void;
    onDelete?: (id: string) => void;
  };
  const registry = useContext(ConditionTypesContext);
  // Sub-condition-only predicates (`player_role`, `player_div`) are rejected at
  // the top level by the validator, so they are not offered here. Before the
  // query resolves the list is empty — keep the node's own type selectable so
  // the control never renders blank.
  const options = useMemo(() => {
    const selectable = registry.filter((option) => !option.subcondition_only);
    if (selectable.length > 0) return selectable;
    return d.conditionType ? [{ name: d.conditionType } as ConditionTypeInfo] : [];
  }, [registry, d.conditionType]);
  const params = d.params ?? {};
  const lostInRoundParam = params.lost_in_round;
  const lostInRound =
    lostInRoundParam !== null && typeof lostInRoundParam === "object"
      ? lostInRoundParam
      : null;
  const lostInRoundOp =
    lostInRound && "op" in lostInRound && typeof lostInRound.op === "string"
      ? lostInRound.op
      : undefined;
  const lostInRoundValue =
    lostInRound && "value" in lostInRound && typeof lostInRound.value === "number"
      ? lostInRound.value
      : 1;

  const setParam = (key: string, value: unknown) => d.onChangeParam?.(id, key, value);
  const label = conditionLabel(d.conditionType);
  const path = d.path ?? "1";
  /**
   * Accessible name for one field inside this node. Thirty-odd param controls
   * share the same handful of field names ("Operator", "Value"), so each one
   * has to carry both its own field and the condition it belongs to.
   */
  const controlName = (field: string) => `${field} for ${label} condition ${path}`;

  if (d.readOnly) {
    const summary = formatParamsSummary(d.conditionType ?? "", params);
    return (
      <div
        className="rounded-lg border-2 px-3 py-2 bg-card shadow-md"
        style={{ borderColor: LEAF_COLOR }}
      >
        <Handle type="target" position={Position.Left} aria-hidden style={{ background: LEAF_COLOR }} />
        <p className="text-xs font-medium">
          <span className="mr-1.5 tabular-nums text-muted-foreground">{path}</span>
          {label}
        </p>
        {summary && <p className="text-xs text-muted-foreground mt-0.5">{summary}</p>}
      </div>
    );
  }

  return (
    <div
      className="rounded-lg border-2 px-3 py-2 bg-card shadow-md space-y-2"
      style={{ borderColor: LEAF_COLOR }}
    >
      <Handle type="target" position={Position.Left} aria-hidden style={{ background: LEAF_COLOR }} />
      <div className="flex items-center gap-2">
        <span className="text-xs tabular-nums text-muted-foreground">{path}</span>
        <Select
          value={d.conditionType ?? "match_win"}
          onValueChange={(val) => d.onChangeType?.(id, val)}
        >
          <SelectTrigger className="h-7 text-xs flex-1" aria-label={`Condition type for condition ${path}`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {options.map((option) => (
              <SelectItem key={option.name} value={option.name}>
                {conditionLabel(option.name)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {d.parentId && (
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={() => d.onDelete?.(id)}
            aria-label={`Delete ${label} condition ${path}`}
          >
            <Trash2 className="h-3.5 w-3.5 text-destructive" aria-hidden />
          </Button>
        )}
      </div>

      {/* Inline param editors */}
      <div className="space-y-1.5 text-xs">
        {(d.conditionType === "stat_threshold" || d.conditionType === "global_stat_sum") && (
          <StatOpValueFields params={params} setParam={setParam} controlName={controlName} />
        )}
        {d.conditionType === "match_criteria" && (
          <>
            <Select value={(params.field as string) ?? ""} onValueChange={(v) => setParam("field", v)}>
              <SelectTrigger className="h-7 text-xs" aria-label={controlName("Field")}><SelectValue placeholder="Field…" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="closeness">Closeness</SelectItem>
                <SelectItem value="match_time">Match time</SelectItem>
              </SelectContent>
            </Select>
            <div className="flex gap-1">
              <Select value={(params.op as string) ?? ">="} onValueChange={(v) => setParam("op", v)}>
                <SelectTrigger className="h-7 text-xs w-16" aria-label={controlName("Operator")}><SelectValue /></SelectTrigger>
                <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
              </Select>
              <NumberInput className="h-7 text-xs" aria-label={controlName("Threshold value")} value={(params.value as number) ?? 0} onValueChange={(next) => setParam("value", next ?? 0)} />
            </div>
          </>
        )}
        {d.conditionType === "player_role" && (
          <Select value={(params.role as string) ?? "Damage"} onValueChange={(v) => setParam("role", v)}>
            <SelectTrigger className="h-7 text-xs" aria-label={controlName("Role")}><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="Tank">Tank</SelectItem>
              <SelectItem value="Damage">Damage</SelectItem>
              <SelectItem value="Support">Support</SelectItem>
            </SelectContent>
          </Select>
        )}
        {d.conditionType === "player_div" && (
          <div className="flex gap-1">
            <Select value={(params.op as string) ?? "=="} onValueChange={(v) => setParam("op", v)}>
              <SelectTrigger className="h-7 text-xs w-16" aria-label={controlName("Operator")}><SelectValue /></SelectTrigger>
              <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
            </Select>
            <NumberInput integer className="h-7 text-xs" aria-label={controlName("Division")} value={(params.value as number) ?? 1} onValueChange={(next) => setParam("value", next ?? 1)} />
          </div>
        )}
        {/* ── op + value conditions ── */}
        {(d.conditionType === "standing_position" || d.conditionType === "tournament_count" || d.conditionType === "div_level") && (
          <div className="flex gap-1">
            <Select value={(params.op as string) ?? "=="} onValueChange={(v) => setParam("op", v)}>
              <SelectTrigger className="h-7 text-xs w-16" aria-label={controlName("Operator")}><SelectValue /></SelectTrigger>
              <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
            </Select>
            <NumberInput integer className="h-7 text-xs" aria-label={controlName("Value")} value={(params.value as number) ?? 1} onValueChange={(next) => setParam("value", next ?? 1)} />
          </div>
        )}
        {/* ── standing_record: field + op + value ── */}
        {d.conditionType === "standing_record" && (
          <>
            <Select value={(params.field as string) ?? "wins"} onValueChange={(v) => setParam("field", v)}>
              <SelectTrigger className="h-7 text-xs" aria-label={controlName("Field")}><SelectValue placeholder="Field…" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="wins">Wins</SelectItem>
                <SelectItem value="losses">Losses</SelectItem>
                <SelectItem value="draws">Draws</SelectItem>
                <SelectItem value="points">Points</SelectItem>
                <SelectItem value="buchholz">Buchholz</SelectItem>
                <SelectItem value="matches">Matches</SelectItem>
              </SelectContent>
            </Select>
            <div className="flex gap-1">
              <Select value={(params.op as string) ?? ">="} onValueChange={(v) => setParam("op", v)}>
                <SelectTrigger className="h-7 text-xs w-16" aria-label={controlName("Operator")}><SelectValue /></SelectTrigger>
                <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
              </Select>
              <NumberInput className="h-7 text-xs" aria-label={controlName("Value")} value={(params.value as number) ?? 0} onValueChange={(next) => setParam("value", next ?? 0)} />
            </div>
          </>
        )}
        {/* ── div_change ── */}
        {d.conditionType === "div_change" && (
          <div className="flex gap-1">
            <Select value={(params.direction as string) ?? "up"} onValueChange={(v) => setParam("direction", v)}>
              <SelectTrigger className="h-7 text-xs" aria-label={controlName("Direction")}><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="up">Up</SelectItem>
                <SelectItem value="down">Down</SelectItem>
              </SelectContent>
            </Select>
            <NumberInput integer className="h-7 text-xs" aria-label={controlName("Minimum shift")} placeholder="Min shift" value={(params.min_shift as number) ?? 1} onValueChange={(next) => setParam("min_shift", next ?? 1)} />
          </div>
        )}
        {/* ── hero_stat: hero + stat + op + value ── */}
        {d.conditionType === "hero_stat" && (
          <>
            <Input className="h-7 text-xs" aria-label={controlName("Hero slug")} placeholder="Hero slug (e.g. dva)" value={(params.hero_slug as string) ?? ""} onChange={(e) => setParam("hero_slug", e.target.value)} />
            <StatOpValueFields params={params} setParam={setParam} controlName={controlName} />
          </>
        )}
        {/* ── hero_kd_best ── */}
        {d.conditionType === "hero_kd_best" && (
          <>
            <Input className="h-7 text-xs" aria-label={controlName("Hero slug")} placeholder="Hero slug" value={(params.hero_slug as string) ?? ""} onChange={(e) => setParam("hero_slug", e.target.value)} />
            <div className="flex gap-1">
              <NumberInput integer className="h-7 text-xs" aria-label={controlName("Minimum time played in seconds")} placeholder="Min time (s)" value={(params.min_time as number) ?? 600} onValueChange={(next) => setParam("min_time", next ?? 600)} />
              <NumberInput integer className="h-7 text-xs" aria-label={controlName("Minimum matches")} placeholder="Min matches" value={(params.min_matches as number) ?? 3} onValueChange={(next) => setParam("min_matches", next ?? 3)} />
            </div>
          </>
        )}
        {/* ── global_winrate: order + limit + op/value ── */}
        {d.conditionType === "global_winrate" && (
          <>
            <div className="flex gap-1">
              <Select value={(params.order as string) ?? "desc"} onValueChange={(v) => setParam("order", v)}>
                <SelectTrigger className="h-7 text-xs" aria-label={controlName("Ranking end")}><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="desc">Top</SelectItem>
                  <SelectItem value="asc">Bottom</SelectItem>
                </SelectContent>
              </Select>
              <NumberInput integer className="h-7 text-xs" aria-label={controlName("Ranking limit")} placeholder="Limit" value={(params.limit as number) ?? 20} onValueChange={(next) => setParam("limit", next ?? 20)} />
            </div>
            <div className="flex gap-1">
              <Select value={(params.op as string) ?? "none"} onValueChange={(v) => setParam("op", v === "none" ? undefined : v)}>
                <SelectTrigger className="h-7 text-xs w-16" aria-label={controlName("Winrate operator")}><SelectValue placeholder="Op" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">None</SelectItem>
                  {OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
                </SelectContent>
              </Select>
              {Boolean(params.op) && <NumberInput className="h-7 text-xs w-16" aria-label={controlName("Winrate")} placeholder="Rate" value={(params.value as number) ?? 0.5} onValueChange={(next) => setParam("value", next ?? 0.5)} />}
            </div>
          </>
        )}
        {/* ── consecutive: metric + streak + day_two position ── */}
        {d.conditionType === "consecutive" && (
          <>
            <div className="flex gap-1">
              <Select value={(params.metric as string) ?? "win"} onValueChange={(v) => setParam("metric", v)}>
                <SelectTrigger className="h-7 text-xs" aria-label={controlName("Streak metric")}><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="win">Win</SelectItem>
                  <SelectItem value="day_two">Day two</SelectItem>
                </SelectContent>
              </Select>
              <NumberInput integer className="h-7 text-xs" aria-label={controlName("Minimum streak")} placeholder="Streak" value={(params.min_streak as number) ?? 2} onValueChange={(next) => setParam("min_streak", next ?? 2)} />
            </div>
            {(params.metric as string) === "day_two" && (
              <div className="flex gap-1 items-center">
                <p className="text-muted-foreground text-xs shrink-0">Position</p>
                <Select value={(params.position_op as string) ?? "<"} onValueChange={(v) => setParam("position_op", v)}>
                  <SelectTrigger className="h-7 text-xs w-16" aria-label={controlName("Position operator")}><SelectValue /></SelectTrigger>
                  <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
                </Select>
                <NumberInput integer className="h-7 text-xs w-14" aria-label={controlName("Position")} value={(params.position_value as number) ?? 7} onValueChange={(next) => setParam("position_value", next ?? 7)} />
              </div>
            )}
          </>
        )}
        {/* ── is_newcomer: bool or count mode ── */}
        {d.conditionType === "is_newcomer" && (
          <div className="flex gap-1">
            <Select
              value={params.op !== undefined ? "count" : "bool"}
              onValueChange={(v) => {
                if (v === "bool") {
                  setParam("op", undefined);
                  setParam("value", undefined);
                } else {
                  setParam("op", params.op ?? ">=");
                  setParam("value", params.value ?? 1);
                }
              }}
            >
              <SelectTrigger className="h-7 text-xs" aria-label={controlName("Newcomer mode")}><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="bool">Is newcomer</SelectItem>
                <SelectItem value="count">Count tournaments</SelectItem>
              </SelectContent>
            </Select>
            {params.op !== undefined && (
              <>
                <Select value={(params.op as string) ?? ">="} onValueChange={(v) => setParam("op", v)}>
                  <SelectTrigger className="h-7 text-xs w-16" aria-label={controlName("Tournament count operator")}><SelectValue /></SelectTrigger>
                  <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
                </Select>
                <NumberInput integer className="h-7 text-xs w-14" aria-label={controlName("Tournament count")} value={(params.value as number) ?? 1} onValueChange={(next) => setParam("value", next ?? 1)} />
              </>
            )}
          </div>
        )}
        {/* ── tournament_type: any/league/not league ── */}
        {d.conditionType === "tournament_type" && (
          <Select
            value={params.is_league === null || params.is_league === undefined ? "any" : String(params.is_league)}
            onValueChange={(v) => setParam("is_league", v === "any" ? null : v === "true")}
          >
            <SelectTrigger className="h-7 text-xs" aria-label={controlName("Tournament type")}><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="any">Any</SelectItem>
              <SelectItem value="true">League</SelectItem>
              <SelectItem value="false">Not league</SelectItem>
            </SelectContent>
          </Select>
        )}
        {/* ── encounter_score: round_type + scores + winner ── */}
        {d.conditionType === "encounter_score" && (
          <>
            <div className="flex gap-1">
              <Select value={(params.round_type as string) ?? "any"} onValueChange={(v) => setParam("round_type", v)}>
                <SelectTrigger className="h-7 text-xs" aria-label={controlName("Round type")}><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="any">Any round</SelectItem>
                  <SelectItem value="final">Final</SelectItem>
                </SelectContent>
              </Select>
              <Select value={String(params.winner ?? true)} onValueChange={(v) => setParam("winner", v === "true")}>
                <SelectTrigger className="h-7 text-xs" aria-label={controlName("Which side counts")}><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="true">Winner only</SelectItem>
                  <SelectItem value="false">Both teams</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <p className="text-muted-foreground text-xs">Score patterns (home–away)</p>
              {((params.scores as number[][]) ?? [[2, 3]]).map((pair, i) => (
                <div key={i} className="flex gap-1 items-center">
                  <NumberInput integer className="h-7 text-xs w-12" aria-label={controlName(`Home score of pattern ${i + 1}`)} value={pair[0]} onValueChange={(next) => {
                    const scores = [...((params.scores as number[][]) ?? [[2, 3]])];
                    scores[i] = [next ?? 0, scores[i][1]];
                    setParam("scores", scores);
                  }} />
                  <span className="text-xs text-muted-foreground" aria-hidden>–</span>
                  <NumberInput integer className="h-7 text-xs w-12" aria-label={controlName(`Away score of pattern ${i + 1}`)} value={pair[1]} onValueChange={(next) => {
                    const scores = [...((params.scores as number[][]) ?? [[2, 3]])];
                    scores[i] = [scores[i][0], next ?? 0];
                    setParam("scores", scores);
                  }} />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    aria-label={controlName(`Remove score pattern ${i + 1}`)}
                    onClick={() => {
                      const scores = ((params.scores as number[][]) ?? [[2, 3]]).filter((_, idx) => idx !== i);
                      setParam("scores", scores.length > 0 ? scores : [[0, 0]]);
                    }}
                  >
                    <X className="h-3 w-3 text-destructive" aria-hidden />
                  </Button>
                </div>
              ))}
              <button
                type="button"
                className="flex items-center gap-1 text-xs text-primary hover:underline"
                aria-label={controlName("Add score pattern")}
                onClick={() => {
                  const scores = [...((params.scores as number[][]) ?? [[2, 3]]), [0, 0]];
                  setParam("scores", scores);
                }}
              >
                <Plus className="h-3 w-3" aria-hidden />
                Add score pattern
              </button>
            </div>
          </>
        )}
        {/* ── match_mvp_check: stat + top_n + team count in top ── */}
        {d.conditionType === "match_mvp_check" && (
          <>
            <div className="flex gap-1">
              <Select value={(params.stat as string) ?? "Performance"} onValueChange={(v) => setParam("stat", v)}>
                <SelectTrigger className="h-7 text-xs" aria-label={controlName("Stat")}><SelectValue placeholder="Stat…" /></SelectTrigger>
                <SelectContent>{STATS.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
              </Select>
              <Select value={(params.sort_order as string) ?? "auto"} onValueChange={(v) => setParam("sort_order", v)}>
                <SelectTrigger className="h-7 text-xs w-20" aria-label={controlName("Sort order")}><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">Auto</SelectItem>
                  <SelectItem value="desc">Desc</SelectItem>
                  <SelectItem value="asc">Asc</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex gap-1 items-center">
              <p className="text-muted-foreground text-xs shrink-0">Top</p>
              <NumberInput integer className="h-7 text-xs w-12" aria-label={controlName("Top N players")} min={1} value={(params.top_n as number) ?? 3} onValueChange={(next) => setParam("top_n", next ?? 3)} />
              <p className="text-muted-foreground text-xs shrink-0">team in top</p>
              <Select value={(params.op as string) ?? "=="} onValueChange={(v) => setParam("op", v)}>
                <SelectTrigger className="h-7 text-xs w-16" aria-label={controlName("Teammates in top operator")}><SelectValue /></SelectTrigger>
                <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
              </Select>
              <NumberInput integer className="h-7 text-xs w-12" aria-label={controlName("Teammates in top")} min={0} value={(params.value as number) ?? 0} onValueChange={(next) => setParam("value", next ?? 0)} />
            </div>
          </>
        )}
        {/* ── bracket_path: lower/upper bracket + options ── */}
        {d.conditionType === "bracket_path" && (
          <>
            <div className="flex gap-1">
              <Select
                value={params.played_upper_bracket === true ? "upper" : "lower"}
                onValueChange={(v) => {
                  if (v === "upper") {
                    setParam("played_lower_bracket", undefined);
                    setParam("played_upper_bracket", true);
                  } else {
                    setParam("played_lower_bracket", true);
                    setParam("played_upper_bracket", undefined);
                  }
                }}
              >
                <SelectTrigger className="h-7 text-xs" aria-label={controlName("Bracket path")}><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="lower">Lower bracket</SelectItem>
                  <SelectItem value="upper">Upper bracket only</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {(params.played_lower_bracket ?? true) && (
              <>
                <div className="flex gap-1 items-center">
                  <p className="text-muted-foreground text-xs shrink-0">Min LB wins</p>
                  <NumberInput integer className="h-7 text-xs w-14" aria-label={controlName("Minimum lower-bracket wins")} value={(params.min_lower_bracket_wins as number) ?? null} placeholder="Any" onValueChange={(next) => setParam("min_lower_bracket_wins", next ?? undefined)} />
                </div>
                <div className="flex gap-1 items-center">
                  <p className="text-muted-foreground text-xs shrink-0">Lost in round</p>
                  <Select value={lostInRoundOp ?? "any"} onValueChange={(v) => setParam("lost_in_round", v !== "any" ? { op: v, value: lostInRoundValue } : undefined)}>
                    <SelectTrigger className="h-7 text-xs w-16" aria-label={controlName("Lost-in-round operator")}><SelectValue placeholder="Any" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="any">Any</SelectItem>
                      {OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  {lostInRoundOp && (
                    <NumberInput integer className="h-7 text-xs w-14" aria-label={controlName("Lost-in-round number")} value={lostInRoundValue} onValueChange={(next) => setParam("lost_in_round", { ...lostInRound, value: next ?? 1 })} />
                  )}
                </div>
              </>
            )}
          </>
        )}
        {/* ── tournament_format: double_elim / single_elim / round_robin ── */}
        {d.conditionType === "tournament_format" && (
          <Select value={(params.format as string) ?? "double_elim"} onValueChange={(v) => setParam("format", v)}>
            <SelectTrigger className="h-7 text-xs" aria-label={controlName("Tournament format")}><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="double_elim">Double elimination</SelectItem>
              <SelectItem value="single_elim">Single elimination</SelectItem>
              <SelectItem value="round_robin">Round robin</SelectItem>
              <SelectItem value="has_bracket">Any bracket</SelectItem>
            </SelectContent>
          </Select>
        )}
        {/* ── distinct_count: field + op + value + scope + min_playtime ── */}
        {d.conditionType === "distinct_count" && (
          <>
            <div className="flex gap-1">
              <Select value={(params.field as string) ?? ""} onValueChange={(v) => setParam("field", v)}>
                <SelectTrigger className="h-7 text-xs" aria-label={controlName("Field")}><SelectValue placeholder="Field" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="role">Role</SelectItem>
                  <SelectItem value="hero">Hero</SelectItem>
                  <SelectItem value="match">Match</SelectItem>
                </SelectContent>
              </Select>
              <Select value={(params.op as string) ?? ">="} onValueChange={(v) => setParam("op", v)}>
                <SelectTrigger className="h-7 text-xs w-16" aria-label={controlName("Operator")}><SelectValue /></SelectTrigger>
                <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
              </Select>
              <NumberInput integer className="h-7 text-xs w-16" aria-label={controlName("Distinct count")} value={(params.value as number) ?? 1} onValueChange={(next) => setParam("value", next ?? 1)} />
            </div>
            <div className="flex gap-1">
              <Select value={(params.scope as string) ?? "global"} onValueChange={(v) => setParam("scope", v)}>
                <SelectTrigger className="h-7 text-xs" aria-label={controlName("Counting scope")}><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="global">Global</SelectItem>
                  <SelectItem value="tournament">Per tournament</SelectItem>
                </SelectContent>
              </Select>
              {(params.field as string) === "hero" && (
                <NumberInput integer className="h-7 text-xs w-20" aria-label={controlName("Minimum hero playtime in seconds")} placeholder="Min time (s)" value={(params.min_playtime as number) ?? null} onValueChange={(next) => setParam("min_playtime", next ?? undefined)} />
              )}
            </div>
          </>
        )}
        {d.conditionType === "stable_streak" && (
          <>
            <div className="space-y-1">
              <p className="text-muted-foreground" id={`${id}-streak-fields`}>Fields</p>
              <div className="flex flex-wrap gap-1" role="group" aria-labelledby={`${id}-streak-fields`}>
                {["role", "division", "team", "hero"].map((f) => {
                  const fields = (params.fields as string[]) ?? [];
                  const active = fields.includes(f);
                  return (
                    <button
                      key={f}
                      type="button"
                      aria-pressed={active}
                      aria-label={controlName(`Track ${f}`)}
                      className={`px-1.5 py-0.5 rounded text-xs border transition-colors ${active ? "bg-primary text-primary-foreground border-primary" : "bg-muted border-border hover:bg-accent"}`}
                      onClick={() => {
                        const next = active ? fields.filter((x) => x !== f) : [...fields, f];
                        setParam("fields", next);
                      }}
                    >
                      {f}
                    </button>
                  );
                })}
              </div>
            </div>
            <div className="flex gap-1 items-center">
              <p className="text-muted-foreground shrink-0">Min streak</p>
              <NumberInput integer className="h-7 text-xs w-16" aria-label={controlName("Minimum streak")} min={2} value={(params.min_streak as number) ?? 2} onValueChange={(next) => setParam("min_streak", next ?? 2)} />
            </div>
          </>
        )}
        {["match_win", "is_captain", "encounter_revenge"].includes(d.conditionType ?? "") && (
          <p className="text-muted-foreground italic">No parameters</p>
        )}
      </div>
    </div>
  );
}

// ─── Sidebar items ───────────────────────────────────────────────────────────

interface SidebarItem {
  type: "logical" | "leaf";
  label: string;
  logicalOp?: string;
  conditionType?: string;
  /** Logical operators only — leaves all share the success tone. */
  color?: string;
}

const SIDEBAR_GROUPS: { label: string; items: SidebarItem[] }[] = [
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

/**
 * Node palette. Dragging onto the canvas is the mouse affordance; every row is
 * also a real button, because a drag gesture is the one interaction a keyboard
 * cannot perform. Clicking appends to the top-level group — the same place a
 * drop lands — after which the node's own buttons move it around.
 */
function DragSidebar({ onAdd }: Readonly<{ onAdd: (item: SidebarItem) => void }>) {
  const [search, setSearch] = useState("");
  const lc = search.toLowerCase();

  const filtered = SIDEBAR_GROUPS.map((g) => ({
    ...g,
    items: g.items.filter((i) => i.label.toLowerCase().includes(lc)),
  })).filter((g) => g.items.length > 0);

  const onDragStart = (e: React.DragEvent, item: SidebarItem) => {
    e.dataTransfer.setData("application/condition-node", JSON.stringify(item));
    e.dataTransfer.effectAllowed = "move";
  };

  return (
    <div className="w-44 h-full overflow-y-auto bg-card/95 backdrop-blur border-r p-2 space-y-2 text-xs">
      <div className="relative">
        <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" aria-hidden />
        <Input
          className="h-7 pl-7 text-xs"
          placeholder="Search nodes…"
          aria-label="Search condition nodes"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <p className="text-xs text-muted-foreground">
        Drag onto the canvas, or click to append to the top-level group.
      </p>
      {filtered.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          No nodes match “{search}”. Try a shorter word such as “stat” or “div”.
        </p>
      ) : null}
      {filtered.map((group) => (
        <div key={group.label}>
          <p className={`${EYEBROW_CLASS} mb-1`}>{group.label}</p>
          <div className="space-y-0.5">
            {group.items.map((item) => (
              <button
                key={item.label}
                type="button"
                draggable
                onDragStart={(e) => onDragStart(e, item)}
                onClick={() => onAdd(item)}
                aria-label={`Add ${item.label} to the condition tree`}
                className="flex w-full items-center gap-1.5 px-2 py-1 rounded text-left cursor-grab hover:bg-accent/50 active:cursor-grabbing transition-colors"
              >
                <GripVertical className="h-3 w-3 text-muted-foreground" aria-hidden />
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ backgroundColor: item.color ?? LEAF_COLOR }}
                  aria-hidden
                />
                <span className="truncate">{item.label}</span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Main component ──────────────────────────────────────────────────────────

export function ConditionFlowEditor(props: Readonly<ConditionFlowEditorProps>) {
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  // The registry only changes when the engine ships a new node, so it is cached
  // for the session rather than refetched per editor mount.
  const { data: conditionTypes } = useQuery({
    queryKey: ["admin", "achievement-condition-types", workspaceId],
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

  const syncTree = useCallback(
    (updated: FlatNode[]) => {
      setFlatNodes(updated);
      const root = updated.find((n) => !n.parentId);
      if (root && onChange) {
        onChange(flatToTree(updated, root.id));
      }
    },
    [onChange],
  );

  const handleChangeOp = useCallback((nodeId: string, op: string) => {
    setFlatNodes((prev) => {
      const updated = prev.map((n) => (n.id === nodeId ? { ...n, logicalOp: op } : n));
      const root = updated.find((n) => !n.parentId);
      if (root && onChange) onChange(flatToTree(updated, root.id));
      return updated;
    });
  }, [onChange]);

  const handleChangeType = useCallback((nodeId: string, type: string) => {
    setFlatNodes((prev) => {
      const updated = prev.map((n) => (n.id === nodeId ? { ...n, conditionType: type, params: {} } : n));
      const root = updated.find((n) => !n.parentId);
      if (root && onChange) onChange(flatToTree(updated, root.id));
      return updated;
    });
  }, [onChange]);

  const handleChangeParam = useCallback((nodeId: string, key: string, val: unknown) => {
    setFlatNodes((prev) => {
      const updated = prev.map((n) =>
        n.id === nodeId ? { ...n, params: { ...(n.params ?? {}), [key]: val } } : n,
      );
      const root = updated.find((n) => !n.parentId);
      if (root && onChange) onChange(flatToTree(updated, root.id));
      return updated;
    });
  }, [onChange]);

  const handleAddChild = useCallback((parentId: string, childType: string) => {
    setFlatNodes((prev) => {
      const newId = getNextNodeId(prev);
      const newNode: FlatNode = childType === "logical"
        ? { id: newId, type: "logical", logicalOp: "AND", parentId }
        : { id: newId, type: "leaf", conditionType: "match_win", params: {}, parentId };
      const updated = [...prev, newNode];
      const root = updated.find((n) => !n.parentId);
      if (root && onChange) onChange(flatToTree(updated, root.id));
      return updated;
    });
  }, [onChange]);

  const handleDelete = useCallback((nodeId: string) => {
    setFlatNodes((prev) => {
      // Remove node and all descendants
      const toRemove = new Set<string>();
      const collect = (id: string) => {
        toRemove.add(id);
        prev.filter((n) => n.parentId === id).forEach((n) => collect(n.id));
      };
      collect(nodeId);
      const updated = prev.filter((n) => !toRemove.has(n.id));
      const root = updated.find((n) => !n.parentId);
      if (root && onChange) onChange(flatToTree(updated, root.id));
      return updated;
    });
  }, [onChange]);

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
      const root = flatNodes.find((n) => !n.parentId);
      if (!root) return;

      // A bare leaf root cannot take children, so wrap it in an AND first.
      if (root.type === "leaf") {
        const newRootId = getNextNodeId(flatNodes, 1);
        const newChildId = getNextNodeId(flatNodes, 2);

        const newRoot: FlatNode = { id: newRootId, type: "logical", logicalOp: "AND" };
        const updatedRoot = { ...root, parentId: newRootId };
        const newChild: FlatNode = item.type === "logical"
          ? { id: newChildId, type: "logical", logicalOp: item.logicalOp ?? "AND", parentId: newRootId }
          : { id: newChildId, type: "leaf", conditionType: item.conditionType ?? "match_win", params: {}, parentId: newRootId };
        const updated = flatNodes.map((n) => (n.id === root.id ? updatedRoot : n));
        updated.unshift(newRoot);
        updated.push(newChild);
        syncTree(updated);
        return;
      }

      const newId = getNextNodeId(flatNodes);
      const newNode: FlatNode = item.type === "logical"
        ? { id: newId, type: "logical", logicalOp: item.logicalOp ?? "AND", parentId: root.id }
        : { id: newId, type: "leaf", conditionType: item.conditionType ?? "match_win", params: {}, parentId: root.id };

      syncTree([...flatNodes, newNode]);
    },
    [flatNodes, syncTree],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const raw = e.dataTransfer.getData("application/condition-node");
      if (!raw) return;
      // Serialised by DragSidebar a moment ago, so the shape is ours.
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
      <TreeOutline nodes={flatNodes} paths={nodePaths} />
      {!readOnly && <DragSidebar onAdd={addPaletteItem} />}
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
