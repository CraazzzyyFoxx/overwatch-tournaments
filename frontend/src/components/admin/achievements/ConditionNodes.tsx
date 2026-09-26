"use client";

import { createContext, useContext, useMemo } from "react";
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
import type { ConditionTypeInfo } from "@/types/admin.types";

import { ConditionLeafFields } from "./ConditionLeafFields";
import {
  HANDLE_COLOR,
  LEAF_COLOR,
  LOGICAL_COLORS,
  conditionLabel,
  formatParamsSummary,
  type FlatNode,
} from "./condition-flow.model";

/**
 * The node types the engine actually implements, served by
 * `achievements/rules/condition-types`. The editor used to keep its own copy,
 * which drifted eight nodes behind the backend; the palette now shows whatever
 * the engine registered, and `required`/`optional` come from the same place the
 * validator reads.
 */
export const ConditionTypesContext = createContext<ConditionTypeInfo[]>([]);

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
  const d = data as unknown as LogicalNodeData;
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

export function LeafNode({ data, id }: NodeProps) {
  const d = data as unknown as LeafNodeData;
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

      <ConditionLeafFields
        nodeId={id}
        conditionType={d.conditionType}
        params={params}
        setParam={setParam}
        controlName={controlName}
      />
    </div>
  );
}
