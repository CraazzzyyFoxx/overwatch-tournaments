"use client";

import { createContext, useContext, type ReactNode } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { FolderPlus, Plus, Trash2 } from "lucide-react";

import { GraphNodeCard } from "@/components/graph-canvas/GraphNodeCard";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { LOGICAL_OPS, type FlatNode } from "./rule-tree";

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

/** The chrome a read-only canvas renders. The builder is engine-agnostic, so
 *  its strings are the caller's to translate. */
export interface RuleBuilderViewLabels {
  outlineTitle: string;
  /** How the outline names one group row, e.g. "1.2 AND group". */
  outlineGroup: (path: string, op: string) => string;
}

/** Everything above plus the strings only an editable canvas renders. */
export interface RuleBuilderEditLabels extends RuleBuilderViewLabels {
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
}

/**
 * Everything one builder instance shares with its nodes.
 *
 * React Flow only hands a node its `data`, and injecting the registry into
 * every node would rebuild the whole layout whenever the catalogue query
 * resolves — so the per-instance registry travels by context, while the
 * per-node callbacks travel in `data`.
 *
 * A read-only builder has no type picker and no parameter form, so the parts
 * that only an editor needs are absent rather than stubbed.
 */
export interface RuleBuilderConfig {
  leafOptions?: RuleLeafOption[];
  defaultLeafType: string;
  labelForLeaf: (type: string | undefined) => string;
  summarizeLeaf: (type: string, params: Record<string, unknown>) => string;
  renderLeafFields?: (props: RuleLeafFieldsProps) => ReactNode;
  labels: RuleBuilderViewLabels;
}

/**
 * The editing strings of a config that is rendering editable nodes.
 *
 * Only a builder constructed with `RuleBuilderEditLabels` ever renders the
 * branches below — `readOnly` nodes return before reaching them — so the
 * narrowing the type system cannot see is restated here once.
 */
function editLabels(config: RuleBuilderConfig): RuleBuilderEditLabels {
  return config.labels as RuleBuilderEditLabels;
}

export const RuleBuilderContext = createContext<RuleBuilderConfig | null>(null);

export function useRuleBuilderConfig(): RuleBuilderConfig {
  const config = useContext(RuleBuilderContext);
  if (config == null) throw new Error("RuleBuilder node rendered outside its provider");
  return config;
}

/** The flat node plus its frame colour, the callbacks and the view flags React Flow carries in `data`. */
type LogicalNodeData = FlatNode & {
  path?: string;
  accent: string;
  readOnly?: boolean;
  onChangeOp?: (id: string, op: string) => void;
  onAddChild?: (id: string, type: string) => void;
  onDelete?: (id: string) => void;
};

type LeafNodeData = FlatNode & {
  path?: string;
  accent: string;
  readOnly?: boolean;
  onChangeType?: (id: string, type: string) => void;
  onChangeParam?: (id: string, key: string, value: unknown) => void;
  onDelete?: (id: string) => void;
};

export function LogicalNode({ data, id, selected }: NodeProps) {
  const config = useRuleBuilderConfig();
  const d = data as unknown as LogicalNodeData;
  const op = d.logicalOp ?? "AND";
  const path = d.path ?? "1";
  const handles = (
    <>
      <Handle type="target" position={Position.Left} aria-hidden />
      <Handle type="source" position={Position.Right} aria-hidden />
    </>
  );

  if (d.readOnly) {
    return (
      <GraphNodeCard accent={d.accent} eyebrow={path} title={<span style={{ color: d.accent }}>{op}</span>} handles={handles} />
    );
  }

  const labels = editLabels(config);
  // Every control below is named by tree position, never by `id` — a node id
  // like "node_7" is a DOM detail and says nothing about which group is meant.
  const groupName = labels.groupName(path);

  return (
    <GraphNodeCard
      accent={d.accent}
      selected={selected}
      eyebrow={path}
      handles={handles}
      title={
        <Select value={op} onValueChange={(val) => d.onChangeOp?.(id, val)}>
          <SelectTrigger size="sm" className="w-20" style={{ color: d.accent }} aria-label={labels.operatorLabel(groupName)}>
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
      }
      actions={
        <>
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
      }
    />
  );
}

export function LeafNode({ data, id, selected }: NodeProps) {
  const config = useRuleBuilderConfig();
  const d = data as unknown as LeafNodeData;
  const leafType = d.leafType ?? config.defaultLeafType;
  const params = d.params ?? {};
  const label = config.labelForLeaf(d.leafType);
  const path = d.path ?? "1";
  const handle = <Handle type="target" position={Position.Left} aria-hidden style={{ background: d.accent }} />;

  if (d.readOnly) {
    const summary = config.summarizeLeaf(leafType, params);
    return (
      <GraphNodeCard accent={d.accent} eyebrow={path} title={label} handles={handle}>
        {summary ? <p className="text-caption text-muted-foreground">{summary}</p> : null}
      </GraphNodeCard>
    );
  }

  const labels = editLabels(config);
  // Before the catalogue resolves the list is empty — keep the node's own type
  // selectable so the control never renders blank.
  const options =
    config.leafOptions && config.leafOptions.length > 0
      ? config.leafOptions
      : [{ value: leafType, label: config.labelForLeaf(leafType) }];

  return (
    <GraphNodeCard
      accent={d.accent}
      selected={selected}
      eyebrow={path}
      handles={handle}
      title={
        <Select value={leafType} onValueChange={(val) => d.onChangeType?.(id, val)}>
          <SelectTrigger size="sm" className="h-7 w-full" aria-label={labels.leafTypeLabel(path)}>
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
      }
      actions={
        d.parentId ? (
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={() => d.onDelete?.(id)}
            aria-label={labels.deleteLeafLabel(label, path)}
          >
            <Trash2 className="h-3.5 w-3.5 text-destructive" aria-hidden />
          </Button>
        ) : null
      }
    >
      {config.renderLeafFields?.({
        nodeId: id,
        leafType: d.leafType,
        params,
        setParam: (key, value) => d.onChangeParam?.(id, key, value),
        controlName: (field) => labels.leafFieldLabel(field, label, path),
      })}
    </GraphNodeCard>
  );
}
