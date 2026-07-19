"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { GripVertical, Maximize2, Minimize2, Plus, Search, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NumberInput } from "@/components/ui/number-input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";

// ─── Constants ───────────────────────────────────────────────────────────────

const OPERATORS = ["==", "!=", ">=", ">", "<=", "<"];
const STATS = [
  "Eliminations", "FinalBlows", "Deaths", "AllDamageDealt", "HeroDamageDealt",
  "HealingDealt", "DamageTaken", "DamageBlocked", "EnvironmentalKills",
  "EnvironmentalDeaths", "ScopedCriticalHitKills", "SoloKills", "CriticalHits",
  "HeroTimePlayed", "UltimatesEarned", "Performance", "KD", "KDA",
];

const CONDITION_TYPES = [
  { value: "stat_threshold", label: "Stat Threshold" },
  { value: "match_criteria", label: "Match Criteria" },
  { value: "match_win", label: "Match Win" },
  { value: "standing_position", label: "Standing Position" },
  { value: "standing_record", label: "Standing Record" },
  { value: "div_change", label: "Division Change" },
  { value: "div_level", label: "Division Level" },
  { value: "is_captain", label: "Is Captain" },
  { value: "is_newcomer", label: "Is Newcomer" },
  { value: "tournament_type", label: "Tournament Type" },
  { value: "hero_kd_best", label: "Hero K/D Best" },
  { value: "hero_stat", label: "Hero Stat" },
  { value: "team_players_match", label: "Team Players Match" },
  { value: "captain_property", label: "Captain Property" },
  { value: "player_role", label: "Player Role" },
  { value: "player_sub_role", label: "Player Sub-role" },
  { value: "player_div", label: "Player Division" },
  { value: "player_flag", label: "Player Flag (Legacy)" },
  { value: "encounter_score", label: "Encounter Score" },
  { value: "encounter_revenge", label: "Encounter Revenge" },
  { value: "bracket_path", label: "Bracket Path" },
  { value: "tournament_format", label: "Tournament Format" },
  { value: "match_mvp_check", label: "Match MVP Check" },
  { value: "global_stat_sum", label: "Global Stat Sum" },
  { value: "tournament_count", label: "Tournament Count" },
  { value: "global_winrate", label: "Global Winrate" },
  { value: "distinct_count", label: "Distinct Count" },
  { value: "consecutive", label: "Consecutive" },
  { value: "stable_streak", label: "Stable Streak" },
];

const LOGICAL_COLORS: Record<string, string> = {
  AND: "#3b82f6",
  OR: "#f59e0b",
  NOT: "#ef4444",
};

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
          stroke: LOGICAL_COLORS[flatNodes.find((n) => n.id === fn.parentId)?.logicalOp ?? "AND"] ?? "#666",
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
  const d = data as unknown as FlatNode & { readOnly?: boolean; onChangeOp?: (id: string, op: string) => void; onAddChild?: (id: string, type: string) => void; onDelete?: (id: string) => void };
  const color = LOGICAL_COLORS[d.logicalOp ?? "AND"];

  return (
    <div
      className="rounded-lg border-2 px-4 py-2 bg-card shadow-md"
      style={{ borderColor: color }}
    >
      <Handle type="target" position={Position.Left} className="!bg-muted-foreground" />
      <div className="flex items-center gap-2">
        {d.readOnly ? (
          <span className="text-xs font-bold px-2" style={{ color }}>{d.logicalOp}</span>
        ) : (
          <Select
            value={d.logicalOp ?? "AND"}
            onValueChange={(val) => d.onChangeOp?.(id, val)}
          >
            <SelectTrigger className="w-20 h-8 text-xs font-bold" style={{ color }}>
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
            >
              <Plus className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => d.onAddChild?.(id, "logical")}
              title="Add group"
            >
              <Badge variant="outline" className="text-[10px] px-1 py-0 cursor-pointer">+G</Badge>
            </Button>
            {d.parentId && (
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                onClick={() => d.onDelete?.(id)}
              >
                <Trash2 className="h-3.5 w-3.5 text-destructive" />
              </Button>
            )}
          </>
        )}
      </div>
      <Handle type="source" position={Position.Right} className="!bg-muted-foreground" />
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
    const fmtLabels: Record<string, string> = { double_elim: "Double Elim", single_elim: "Single Elim", round_robin: "Round Robin", has_bracket: "Any Bracket" };
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
  if (type === "player_sub_role") parts.push(`sub-role: ${params.sub_role ?? ""}`);
  if (type === "player_flag") parts.push(`flag: ${params.flag ?? ""}`);
  if (type === "player_div") parts.push(`div ${params.op ?? "=="} ${params.value ?? ""}`);
  if (params.fields && type === "stable_streak") {
    const fields = params.fields as string[];
    parts.push(`[${fields.join(", ")}] streak >= ${params.min_streak ?? 2}`);
  }
  return parts.join(", ");
}

function LeafNode({ data, id }: NodeProps) {
  const d = data as unknown as FlatNode & { readOnly?: boolean; onChangeType?: (id: string, type: string) => void; onChangeParam?: (id: string, key: string, value: unknown) => void; onDelete?: (id: string) => void };
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
  const label = CONDITION_TYPES.find((ct) => ct.value === d.conditionType)?.label ?? d.conditionType;

  if (d.readOnly) {
    const summary = formatParamsSummary(d.conditionType ?? "", params);
    return (
      <div className="rounded-lg border-2 border-green-500/50 px-3 py-2 bg-card shadow-md">
        <Handle type="target" position={Position.Left} className="!bg-green-500" />
        <p className="text-xs font-medium">{label}</p>
        {summary && <p className="text-xs text-muted-foreground mt-0.5">{summary}</p>}
      </div>
    );
  }

  return (
    <div className="rounded-lg border-2 border-green-500/50 px-3 py-2 bg-card shadow-md space-y-2">
      <Handle type="target" position={Position.Left} className="!bg-green-500" />
      <div className="flex items-center gap-2">
        <Select
          value={d.conditionType ?? "match_win"}
          onValueChange={(val) => d.onChangeType?.(id, val)}
        >
          <SelectTrigger className="h-7 text-xs flex-1">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CONDITION_TYPES.map((ct) => (
              <SelectItem key={ct.value} value={ct.value}>{ct.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {d.parentId && (
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => d.onDelete?.(id)}>
            <Trash2 className="h-3.5 w-3.5 text-destructive" />
          </Button>
        )}
      </div>

      {/* Inline param editors */}
      <div className="space-y-1.5 text-xs">
        {(d.conditionType === "stat_threshold" || d.conditionType === "global_stat_sum") && (
          <>
            <Select value={(params.stat as string) ?? ""} onValueChange={(v) => setParam("stat", v)}>
              <SelectTrigger className="h-7 text-xs"><SelectValue placeholder="Stat..." /></SelectTrigger>
              <SelectContent>{STATS.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
            </Select>
            <div className="flex gap-1">
              <Select value={(params.op as string) ?? ">="} onValueChange={(v) => setParam("op", v)}>
                <SelectTrigger className="h-7 text-xs w-16"><SelectValue /></SelectTrigger>
                <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
              </Select>
              <NumberInput className="h-7 text-xs" value={(params.value as number) ?? 0} onValueChange={(next) => setParam("value", next ?? 0)} />
            </div>
          </>
        )}
        {d.conditionType === "match_criteria" && (
          <>
            <Select value={(params.field as string) ?? ""} onValueChange={(v) => setParam("field", v)}>
              <SelectTrigger className="h-7 text-xs"><SelectValue placeholder="Field..." /></SelectTrigger>
              <SelectContent>
                <SelectItem value="closeness">Closeness</SelectItem>
                <SelectItem value="match_time">Match Time</SelectItem>
              </SelectContent>
            </Select>
            <div className="flex gap-1">
              <Select value={(params.op as string) ?? ">="} onValueChange={(v) => setParam("op", v)}>
                <SelectTrigger className="h-7 text-xs w-16"><SelectValue /></SelectTrigger>
                <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
              </Select>
              <NumberInput className="h-7 text-xs" value={(params.value as number) ?? 0} onValueChange={(next) => setParam("value", next ?? 0)} />
            </div>
          </>
        )}
        {d.conditionType === "player_role" && (
          <Select value={(params.role as string) ?? "Damage"} onValueChange={(v) => setParam("role", v)}>
            <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="Tank">Tank</SelectItem>
              <SelectItem value="Damage">Damage</SelectItem>
              <SelectItem value="Support">Support</SelectItem>
            </SelectContent>
          </Select>
        )}
        {d.conditionType === "player_sub_role" && (
          <Input
            className="h-7 text-xs"
            value={(params.sub_role as string) ?? ""}
            placeholder="e.g. hitscan"
            onChange={(e) => setParam("sub_role", e.target.value)}
          />
        )}
        {d.conditionType === "player_flag" && (
          <Select value={(params.flag as string) ?? "primary"} onValueChange={(v) => setParam("flag", v)}>
            <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="primary">Primary</SelectItem>
              <SelectItem value="secondary">Secondary</SelectItem>
            </SelectContent>
          </Select>
        )}
        {d.conditionType === "player_div" && (
          <div className="flex gap-1">
            <Select value={(params.op as string) ?? "=="} onValueChange={(v) => setParam("op", v)}>
              <SelectTrigger className="h-7 text-xs w-16"><SelectValue /></SelectTrigger>
              <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
            </Select>
            <NumberInput integer className="h-7 text-xs" value={(params.value as number) ?? 1} onValueChange={(next) => setParam("value", next ?? 1)} />
          </div>
        )}
        {/* ── op + value conditions ── */}
        {(d.conditionType === "standing_position" || d.conditionType === "tournament_count" || d.conditionType === "div_level") && (
          <div className="flex gap-1">
            <Select value={(params.op as string) ?? "=="} onValueChange={(v) => setParam("op", v)}>
              <SelectTrigger className="h-7 text-xs w-16"><SelectValue /></SelectTrigger>
              <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
            </Select>
            <NumberInput integer className="h-7 text-xs" value={(params.value as number) ?? 1} onValueChange={(next) => setParam("value", next ?? 1)} />
          </div>
        )}
        {/* ── standing_record: field + op + value ── */}
        {d.conditionType === "standing_record" && (
          <>
            <Select value={(params.field as string) ?? "wins"} onValueChange={(v) => setParam("field", v)}>
              <SelectTrigger className="h-7 text-xs"><SelectValue placeholder="Field..." /></SelectTrigger>
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
                <SelectTrigger className="h-7 text-xs w-16"><SelectValue /></SelectTrigger>
                <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
              </Select>
              <NumberInput className="h-7 text-xs" value={(params.value as number) ?? 0} onValueChange={(next) => setParam("value", next ?? 0)} />
            </div>
          </>
        )}
        {/* ── div_change ── */}
        {d.conditionType === "div_change" && (
          <div className="flex gap-1">
            <Select value={(params.direction as string) ?? "up"} onValueChange={(v) => setParam("direction", v)}>
              <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="up">Up</SelectItem>
                <SelectItem value="down">Down</SelectItem>
              </SelectContent>
            </Select>
            <NumberInput integer className="h-7 text-xs" placeholder="min shift" value={(params.min_shift as number) ?? 1} onValueChange={(next) => setParam("min_shift", next ?? 1)} />
          </div>
        )}
        {/* ── hero_stat: hero + stat + op + value ── */}
        {d.conditionType === "hero_stat" && (
          <>
            <Input className="h-7 text-xs" placeholder="hero slug (e.g. dva)" value={(params.hero_slug as string) ?? ""} onChange={(e) => setParam("hero_slug", e.target.value)} />
            <Select value={(params.stat as string) ?? ""} onValueChange={(v) => setParam("stat", v)}>
              <SelectTrigger className="h-7 text-xs"><SelectValue placeholder="Stat..." /></SelectTrigger>
              <SelectContent>{STATS.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
            </Select>
            <div className="flex gap-1">
              <Select value={(params.op as string) ?? ">="} onValueChange={(v) => setParam("op", v)}>
                <SelectTrigger className="h-7 text-xs w-16"><SelectValue /></SelectTrigger>
                <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
              </Select>
              <NumberInput className="h-7 text-xs" value={(params.value as number) ?? 0} onValueChange={(next) => setParam("value", next ?? 0)} />
            </div>
          </>
        )}
        {/* ── hero_kd_best ── */}
        {d.conditionType === "hero_kd_best" && (
          <>
            <Input className="h-7 text-xs" placeholder="hero slug" value={(params.hero_slug as string) ?? ""} onChange={(e) => setParam("hero_slug", e.target.value)} />
            <div className="flex gap-1">
              <NumberInput integer className="h-7 text-xs" placeholder="min time" value={(params.min_time as number) ?? 600} onValueChange={(next) => setParam("min_time", next ?? 600)} />
              <NumberInput integer className="h-7 text-xs" placeholder="min matches" value={(params.min_matches as number) ?? 3} onValueChange={(next) => setParam("min_matches", next ?? 3)} />
            </div>
          </>
        )}
        {/* ── global_winrate: order + limit + op/value ── */}
        {d.conditionType === "global_winrate" && (
          <>
            <div className="flex gap-1">
              <Select value={(params.order as string) ?? "desc"} onValueChange={(v) => setParam("order", v)}>
                <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="desc">Top</SelectItem>
                  <SelectItem value="asc">Bottom</SelectItem>
                </SelectContent>
              </Select>
              <NumberInput integer className="h-7 text-xs" placeholder="limit" value={(params.limit as number) ?? 20} onValueChange={(next) => setParam("limit", next ?? 20)} />
            </div>
            <div className="flex gap-1">
              <Select value={(params.op as string) ?? "none"} onValueChange={(v) => setParam("op", v === "none" ? undefined : v)}>
                <SelectTrigger className="h-7 text-xs w-16"><SelectValue placeholder="Op" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">None</SelectItem>
                  {OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
                </SelectContent>
              </Select>
              {Boolean(params.op) && <NumberInput className="h-7 text-xs w-16" placeholder="rate" value={(params.value as number) ?? 0.5} onValueChange={(next) => setParam("value", next ?? 0.5)} />}
            </div>
          </>
        )}
        {/* ── consecutive: metric + streak + day_two position ── */}
        {d.conditionType === "consecutive" && (
          <>
            <div className="flex gap-1">
              <Select value={(params.metric as string) ?? "win"} onValueChange={(v) => setParam("metric", v)}>
                <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="win">Win</SelectItem>
                  <SelectItem value="day_two">Day Two</SelectItem>
                </SelectContent>
              </Select>
              <NumberInput integer className="h-7 text-xs" placeholder="streak" value={(params.min_streak as number) ?? 2} onValueChange={(next) => setParam("min_streak", next ?? 2)} />
            </div>
            {(params.metric as string) === "day_two" && (
              <div className="flex gap-1 items-center">
                <p className="text-muted-foreground text-[10px] shrink-0">Position</p>
                <Select value={(params.position_op as string) ?? "<"} onValueChange={(v) => setParam("position_op", v)}>
                  <SelectTrigger className="h-7 text-xs w-16"><SelectValue /></SelectTrigger>
                  <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
                </Select>
                <NumberInput integer className="h-7 text-xs w-14" value={(params.position_value as number) ?? 7} onValueChange={(next) => setParam("position_value", next ?? 7)} />
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
              <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="bool">Is newcomer</SelectItem>
                <SelectItem value="count">Count tournaments</SelectItem>
              </SelectContent>
            </Select>
            {params.op !== undefined && (
              <>
                <Select value={(params.op as string) ?? ">="} onValueChange={(v) => setParam("op", v)}>
                  <SelectTrigger className="h-7 text-xs w-16"><SelectValue /></SelectTrigger>
                  <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
                </Select>
                <NumberInput integer className="h-7 text-xs w-14" value={(params.value as number) ?? 1} onValueChange={(next) => setParam("value", next ?? 1)} />
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
            <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="any">Any</SelectItem>
              <SelectItem value="true">League</SelectItem>
              <SelectItem value="false">Not League</SelectItem>
            </SelectContent>
          </Select>
        )}
        {/* ── encounter_score: round_type + scores + winner ── */}
        {d.conditionType === "encounter_score" && (
          <>
            <div className="flex gap-1">
              <Select value={(params.round_type as string) ?? "any"} onValueChange={(v) => setParam("round_type", v)}>
                <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="any">Any round</SelectItem>
                  <SelectItem value="final">Final</SelectItem>
                </SelectContent>
              </Select>
              <Select value={String(params.winner ?? true)} onValueChange={(v) => setParam("winner", v === "true")}>
                <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="true">Winner only</SelectItem>
                  <SelectItem value="false">Both teams</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <p className="text-muted-foreground text-[10px]">Score patterns (home-away)</p>
              {((params.scores as number[][]) ?? [[2, 3]]).map((pair, i) => (
                <div key={i} className="flex gap-1 items-center">
                  <NumberInput integer className="h-7 text-xs w-12" value={pair[0]} onValueChange={(next) => {
                    const scores = [...((params.scores as number[][]) ?? [[2, 3]])];
                    scores[i] = [next ?? 0, scores[i][1]];
                    setParam("scores", scores);
                  }} />
                  <span className="text-xs text-muted-foreground">-</span>
                  <NumberInput integer className="h-7 text-xs w-12" value={pair[1]} onValueChange={(next) => {
                    const scores = [...((params.scores as number[][]) ?? [[2, 3]])];
                    scores[i] = [scores[i][0], next ?? 0];
                    setParam("scores", scores);
                  }} />
                  <button type="button" className="text-destructive text-xs" onClick={() => {
                    const scores = ((params.scores as number[][]) ?? [[2, 3]]).filter((_, idx) => idx !== i);
                    setParam("scores", scores.length > 0 ? scores : [[0, 0]]);
                  }}>x</button>
                </div>
              ))}
              <button type="button" className="text-xs text-primary hover:underline" onClick={() => {
                const scores = [...((params.scores as number[][]) ?? [[2, 3]]), [0, 0]];
                setParam("scores", scores);
              }}>+ Add score pattern</button>
            </div>
          </>
        )}
        {/* ── match_mvp_check: stat + top_n + team count in top ── */}
        {d.conditionType === "match_mvp_check" && (
          <>
            <div className="flex gap-1">
              <Select value={(params.stat as string) ?? "Performance"} onValueChange={(v) => setParam("stat", v)}>
                <SelectTrigger className="h-7 text-xs"><SelectValue placeholder="Stat..." /></SelectTrigger>
                <SelectContent>{STATS.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
              </Select>
              <Select value={(params.sort_order as string) ?? "auto"} onValueChange={(v) => setParam("sort_order", v)}>
                <SelectTrigger className="h-7 text-xs w-20"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">Auto</SelectItem>
                  <SelectItem value="desc">Desc</SelectItem>
                  <SelectItem value="asc">Asc</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex gap-1 items-center">
              <p className="text-muted-foreground text-[10px] shrink-0">Top</p>
              <NumberInput integer className="h-7 text-xs w-12" min={1} value={(params.top_n as number) ?? 3} onValueChange={(next) => setParam("top_n", next ?? 3)} />
              <p className="text-muted-foreground text-[10px] shrink-0">team in top</p>
              <Select value={(params.op as string) ?? "=="} onValueChange={(v) => setParam("op", v)}>
                <SelectTrigger className="h-7 text-xs w-16"><SelectValue /></SelectTrigger>
                <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
              </Select>
              <NumberInput integer className="h-7 text-xs w-12" min={0} value={(params.value as number) ?? 0} onValueChange={(next) => setParam("value", next ?? 0)} />
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
                <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="lower">Lower bracket</SelectItem>
                  <SelectItem value="upper">Upper bracket only</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {(params.played_lower_bracket ?? true) && (
              <>
                <div className="flex gap-1 items-center">
                  <p className="text-muted-foreground text-[10px] shrink-0">Min LB wins</p>
                  <NumberInput integer className="h-7 text-xs w-14" value={(params.min_lower_bracket_wins as number) ?? null} placeholder="any" onValueChange={(next) => setParam("min_lower_bracket_wins", next ?? undefined)} />
                </div>
                <div className="flex gap-1 items-center">
                  <p className="text-muted-foreground text-[10px] shrink-0">Lost in round</p>
                  <Select value={lostInRoundOp ?? "any"} onValueChange={(v) => setParam("lost_in_round", v !== "any" ? { op: v, value: lostInRoundValue } : undefined)}>
                    <SelectTrigger className="h-7 text-xs w-16"><SelectValue placeholder="any" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="any">Any</SelectItem>
                      {OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  {lostInRoundOp && (
                    <NumberInput integer className="h-7 text-xs w-14" value={lostInRoundValue} onValueChange={(next) => setParam("lost_in_round", { ...lostInRound, value: next ?? 1 })} />
                  )}
                </div>
              </>
            )}
          </>
        )}
        {/* ── tournament_format: double_elim / single_elim / round_robin ── */}
        {d.conditionType === "tournament_format" && (
          <Select value={(params.format as string) ?? "double_elim"} onValueChange={(v) => setParam("format", v)}>
            <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="double_elim">Double Elimination</SelectItem>
              <SelectItem value="single_elim">Single Elimination</SelectItem>
              <SelectItem value="round_robin">Round Robin</SelectItem>
              <SelectItem value="has_bracket">Any Bracket</SelectItem>
            </SelectContent>
          </Select>
        )}
        {/* ── distinct_count: field + op + value + scope + min_playtime ── */}
        {d.conditionType === "distinct_count" && (
          <>
            <div className="flex gap-1">
              <Select value={(params.field as string) ?? ""} onValueChange={(v) => setParam("field", v)}>
                <SelectTrigger className="h-7 text-xs"><SelectValue placeholder="Field" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="role">Role</SelectItem>
                  <SelectItem value="hero">Hero</SelectItem>
                  <SelectItem value="match">Match</SelectItem>
                </SelectContent>
              </Select>
              <Select value={(params.op as string) ?? ">="} onValueChange={(v) => setParam("op", v)}>
                <SelectTrigger className="h-7 text-xs w-16"><SelectValue /></SelectTrigger>
                <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
              </Select>
              <NumberInput integer className="h-7 text-xs w-16" value={(params.value as number) ?? 1} onValueChange={(next) => setParam("value", next ?? 1)} />
            </div>
            <div className="flex gap-1">
              <Select value={(params.scope as string) ?? "global"} onValueChange={(v) => setParam("scope", v)}>
                <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="global">Global</SelectItem>
                  <SelectItem value="tournament">Per tournament</SelectItem>
                </SelectContent>
              </Select>
              {(params.field as string) === "hero" && (
                <NumberInput integer className="h-7 text-xs w-20" placeholder="min time (s)" value={(params.min_playtime as number) ?? null} onValueChange={(next) => setParam("min_playtime", next ?? undefined)} />
              )}
            </div>
          </>
        )}
        {d.conditionType === "stable_streak" && (
          <>
            <div className="space-y-1">
              <p className="text-muted-foreground">Fields</p>
              <div className="flex flex-wrap gap-1">
                {["role", "division", "team", "hero"].map((f) => {
                  const fields = (params.fields as string[]) ?? [];
                  const active = fields.includes(f);
                  return (
                    <button
                      key={f}
                      type="button"
                      className={`px-1.5 py-0.5 rounded text-[10px] border transition-colors ${active ? "bg-primary text-primary-foreground border-primary" : "bg-muted border-border hover:bg-accent"}`}
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
              <NumberInput integer className="h-7 text-xs w-16" min={2} value={(params.min_streak as number) ?? 2} onValueChange={(next) => setParam("min_streak", next ?? 2)} />
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

// ─── Main Component ──────────────────────────────────────────────────────────

// ─── Sidebar items for drag-and-drop ─────────────────────────────────────────

const SIDEBAR_GROUPS = [
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
      { type: "leaf", conditionType: "stat_threshold", label: "Stat Threshold" },
      { type: "leaf", conditionType: "match_criteria", label: "Match Criteria" },
      { type: "leaf", conditionType: "match_win", label: "Match Win" },
      { type: "leaf", conditionType: "hero_stat", label: "Hero Stat" },
      { type: "leaf", conditionType: "match_mvp_check", label: "MVP Check" },
    ],
  },
  {
    label: "Tournament",
    items: [
      { type: "leaf", conditionType: "standing_position", label: "Position" },
      { type: "leaf", conditionType: "standing_record", label: "Record" },
      { type: "leaf", conditionType: "div_change", label: "Division Change" },
      { type: "leaf", conditionType: "div_level", label: "Division Level" },
      { type: "leaf", conditionType: "is_captain", label: "Is Captain" },
      { type: "leaf", conditionType: "is_newcomer", label: "Is Newcomer" },
      { type: "leaf", conditionType: "tournament_type", label: "Tournament Type" },
      { type: "leaf", conditionType: "hero_kd_best", label: "Hero K/D Best" },
      { type: "leaf", conditionType: "team_players_match", label: "Team Players" },
      { type: "leaf", conditionType: "captain_property", label: "Captain Prop" },
      { type: "leaf", conditionType: "encounter_score", label: "Encounter Score" },
      { type: "leaf", conditionType: "encounter_revenge", label: "Encounter Revenge" },
      { type: "leaf", conditionType: "bracket_path", label: "Bracket Path" },
      { type: "leaf", conditionType: "tournament_format", label: "Format" },
    ],
  },
  {
    label: "Global",
    items: [
      { type: "leaf", conditionType: "global_stat_sum", label: "Global Stat Sum" },
      { type: "leaf", conditionType: "tournament_count", label: "Tournament Count" },
      { type: "leaf", conditionType: "global_winrate", label: "Global Winrate" },
      { type: "leaf", conditionType: "distinct_count", label: "Distinct Count" },
      { type: "leaf", conditionType: "consecutive", label: "Consecutive" },
      { type: "leaf", conditionType: "stable_streak", label: "Stable Streak" },
    ],
  },
];

function DragSidebar() {
  const [search, setSearch] = useState("");
  const lc = search.toLowerCase();

  const filtered = SIDEBAR_GROUPS.map((g) => ({
    ...g,
    items: g.items.filter((i) => i.label.toLowerCase().includes(lc)),
  })).filter((g) => g.items.length > 0);

  const onDragStart = (e: React.DragEvent, item: (typeof SIDEBAR_GROUPS)[0]["items"][0]) => {
    e.dataTransfer.setData("application/condition-node", JSON.stringify(item));
    e.dataTransfer.effectAllowed = "move";
  };

  return (
    <div className="w-44 h-full overflow-y-auto bg-card/95 backdrop-blur border-r p-2 space-y-2 text-xs">
      <div className="relative">
        <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
        <Input
          className="h-7 pl-7 text-xs"
          placeholder="Search nodes..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      {filtered.map((group) => (
        <div key={group.label}>
          <p className="text-[10px] uppercase text-muted-foreground font-medium tracking-wider mb-1">
            {group.label}
          </p>
          <div className="space-y-0.5">
            {group.items.map((item) => (
              <div
                key={item.label}
                className="flex items-center gap-1.5 px-2 py-1 rounded cursor-grab hover:bg-accent/50 active:cursor-grabbing transition-colors"
                draggable
                onDragStart={(e) => onDragStart(e, item)}
              >
                <GripVertical className="h-3 w-3 text-muted-foreground/50" />
                <div
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ backgroundColor: (item as { color?: string }).color ?? "#22c55e" }}
                />
                <span className="truncate">{item.label}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Main Component (inner, needs ReactFlowProvider) ─────────────────────────

export function ConditionFlowEditor(props: ConditionFlowEditorProps) {
  if (props.readOnly) {
    return <ConditionFlowEditorInner {...props} />;
  }
  return (
    <ReactFlowProvider>
      <ConditionFlowEditorInner {...props} />
    </ReactFlowProvider>
  );
}

function ConditionFlowEditorInner({ value, onChange, readOnly = false }: ConditionFlowEditorProps) {
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

  // Build React Flow nodes/edges with callbacks injected into data
  const { nodes: flowNodes, edges: flowEdges } = useMemo(() => {
    const enriched = flatNodes.map((fn) => ({
      ...fn,
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
  }, [flatNodes, readOnly, handleChangeOp, handleChangeType, handleChangeParam, handleAddChild, handleDelete]);

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

  // ─── Drag-and-drop from sidebar ───────────────────────────────────────────

  const wrapperRef = useRef<HTMLDivElement>(null);

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const raw = e.dataTransfer.getData("application/condition-node");
      if (!raw) return;

      const item = JSON.parse(raw) as { type: string; logicalOp?: string; conditionType?: string };

      // Find the closest logical parent to attach to.
      // Default: attach to the root node.
      const root = flatNodes.find((n) => !n.parentId);
      if (!root) return;

      // If root is a leaf and we're adding, wrap root in AND first
      let parentId = root.id;
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

      // Attach to root logical node
      const newId = getNextNodeId(flatNodes);
      const newNode: FlatNode = item.type === "logical"
        ? { id: newId, type: "logical", logicalOp: item.logicalOp ?? "AND", parentId }
        : { id: newId, type: "leaf", conditionType: item.conditionType ?? "match_win", params: {}, parentId };

      syncTree([...flatNodes, newNode]);
    },
    [flatNodes, syncTree],
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
    : `${readOnly ? "h-[300px]" : "h-[500px]"} w-full rounded-lg border bg-background flex`;

  return (
    <div className={containerClass}>
      {!readOnly && <DragSidebar />}
      <div className="flex-1 relative" ref={wrapperRef}>
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
                return "#22c55e";
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
            >
              {fullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
            </Button>
          </Panel>
        </ReactFlow>
      </div>
    </div>
  );
}
