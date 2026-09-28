"use client";

import { createContext, useContext, type ReactNode } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { FolderPlus, Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import {
  HANDLE_COLOR,
  LEAF_COLOR,
  LOGICAL_COLORS,
  LOGICAL_OPS,
  type FlatNode,
} from "./rule-tree";

/** One leaf type the builder offers, as the type `<Select>` renders it. */
export interface RuleLeafOption {
  value: string;
  label: string;
  description?: string;
}

/** The props a caller's parameter form receives for one leaf node. */
export interface RuleLeafFieldsProps {
  nodeId: string;
  leafType: string | undefined;
  params: Record<string, unknown>;
  setParam: (key: string, value: unknown) => void;
  /**
   * Accessible name for one field inside this node. Param controls across the
   * canvas share the same handful of field names ("Operator", "Value"), so
   * each one has to carry both its own field and the leaf it belongs to.
   */
  controlName: (field: string) => string;
}

/** Every string the canvas itself renders. The builder is engine-agnostic, so
 *  its chrome is the caller's to translate. */
export interface RuleBuilderLabels {
  outlineTitle: string;
  /** How the outline names one group row, e.g. "1.2 AND group". */
  outlineGroup: (path: string, op: string) => string;
  paletteSearchPlaceholder: string;
  paletteSearchLabel: string;
  paletteHint: string;
  paletteEmpty: (query: string) => string;
  paletteAdd: (item: string) => string;
  /** "group 1.2" — the noun the group-scoped names below are built from. */
  groupName: (path: string) => string;
  operatorLabel: (group: string) => string;
  addLeaf: string;
  addLeafLabel: (group: string) => string;
  addGroup: string;
  addGroupLabel: (group: string) => string;
  deleteGroupLabel: (group: string) => string;
  deleteLeafLabel: (leafLabel: string, path: string) => string;
  leafTypeLabel: (path: string) => string;
  /** Accessible name of one parameter control inside a leaf node. */
  leafFieldLabel: (field: string, leafLabel: string, path: string) => string;
  fullscreen: string;
  fullscreenLabel: string;
  exitFullscreen: string;
  exitFullscreenLabel: string;
}

/**
 * Everything one builder instance shares with its nodes.
 *
 * React Flow only hands a node its `data`, and injecting the registry into
 * every node would rebuild the whole layout whenever the catalogue query
 * resolves — so the per-instance registry travels by context, while the
 * per-node callbacks travel in `data`.
 */
export interface RuleBuilderConfig {
  leafOptions: RuleLeafOption[];
  defaultLeafType: string;
  labelForLeaf: (type: string | undefined) => string;
  summarizeLeaf: (type: string, params: Record<string, unknown>) => string;
  renderLeafFields: (props: RuleLeafFieldsProps) => ReactNode;
  labels: RuleBuilderLabels;
}

export const RuleBuilderContext = createContext<RuleBuilderConfig | null>(null);

export function useRuleBuilderConfig(): RuleBuilderConfig {
  const config = useContext(RuleBuilderContext);
  if (config == null) throw new Error("RuleBuilder node rendered outside its provider");
  return config;
}

/** The flat node plus the callbacks and view flags React Flow carries in `data`. */
type LogicalNodeData = FlatNode & {
  path?: string;
  readOnly?: boolean;
  onChangeOp?: (id: string, op: string) => void;
  onAddChild?: (id: string, type: string) => void;
  onDelete?: (id: string) => void;
};

type LeafNodeData = FlatNode & {
  path?: string;
  readOnly?: boolean;
  onChangeType?: (id: string, type: string) => void;
  onChangeParam?: (id: string, key: string, value: unknown) => void;
  onDelete?: (id: string) => void;
};

export function LogicalNode({ data, id }: NodeProps) {
  const { labels } = useRuleBuilderConfig();
  const d = data as unknown as LogicalNodeData;
  const op = d.logicalOp ?? "AND";
  const color = LOGICAL_COLORS[op];
  // Every control below is named by tree position, never by `id` — a node id
  // like "node_7" is a DOM detail and says nothing about which group is meant.
  const groupName = labels.groupName(d.path ?? "1");

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
              aria-label={labels.operatorLabel(groupName)}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {LOGICAL_OPS.map((value) => (
                <SelectItem key={value} value={value}>
                  {value}
                </SelectItem>
              ))}
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
              title={labels.addLeaf}
              aria-label={labels.addLeafLabel(groupName)}
            >
              <Plus className="h-3.5 w-3.5" aria-hidden />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => d.onAddChild?.(id, "logical")}
              title={labels.addGroup}
              aria-label={labels.addGroupLabel(groupName)}
            >
              <FolderPlus className="h-3.5 w-3.5" aria-hidden />
            </Button>
            {d.parentId && (
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                onClick={() => d.onDelete?.(id)}
                aria-label={labels.deleteGroupLabel(groupName)}
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

export function LeafNode({ data, id }: NodeProps) {
  const config = useRuleBuilderConfig();
  const d = data as unknown as LeafNodeData;
  const leafType = d.leafType ?? config.defaultLeafType;
  // Before the catalogue resolves the list is empty — keep the node's own type
  // selectable so the control never renders blank.
  const options =
    config.leafOptions.length > 0
      ? config.leafOptions
      : [{ value: leafType, label: config.labelForLeaf(leafType) }];
  const params = d.params ?? {};

  const setParam = (key: string, value: unknown) => d.onChangeParam?.(id, key, value);
  const label = config.labelForLeaf(d.leafType);
  const path = d.path ?? "1";
  const controlName = (field: string) => config.labels.leafFieldLabel(field, label, path);

  if (d.readOnly) {
    const summary = config.summarizeLeaf(leafType, params);
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
        <Select value={leafType} onValueChange={(val) => d.onChangeType?.(id, val)}>
          <SelectTrigger className="h-7 text-xs flex-1" aria-label={config.labels.leafTypeLabel(path)}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {options.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
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
            aria-label={config.labels.deleteLeafLabel(label, path)}
          >
            <Trash2 className="h-3.5 w-3.5 text-destructive" aria-hidden />
          </Button>
        )}
      </div>

      {config.renderLeafFields({ nodeId: id, leafType: d.leafType, params, setParam, controlName })}
    </div>
  );
}
