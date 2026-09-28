"use client";

import { useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { RuleBuilder, type RuleLeafFieldsProps } from "@/components/rule-builder";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { achievementQueryKeys } from "@/lib/achievements/query-keys";

import { ConditionLeafFields } from "./ConditionLeafFields";
import {
  DEFAULT_CONDITION_TYPE,
  SIDEBAR_GROUPS,
  conditionLabel,
  formatParamsSummary,
} from "./condition-flow.model";

/** The canvas chrome, in the editor's own voice. Achievements are admin-only
 *  and English throughout, so these are literals rather than message keys. */
const LABELS = {
  outlineTitle: "Condition tree outline",
  outlineGroup: (path: string, op: string) => `${path} ${op} group`,
  paletteSearchPlaceholder: "Search nodes…",
  paletteSearchLabel: "Search condition nodes",
  paletteHint: "Drag onto the canvas, or click to append to the top-level group.",
  paletteEmpty: (query: string) =>
    `No nodes match “${query}”. Try a shorter word such as “stat” or “div”.`,
  paletteAdd: (item: string) => `Add ${item} to the condition tree`,
  groupName: (path: string) => `group ${path}`,
  operatorLabel: (group: string) => `Logic operator for ${group}`,
  addLeaf: "Add condition",
  addLeafLabel: (group: string) => `Add condition inside ${group}`,
  addGroup: "Add group",
  addGroupLabel: (group: string) => `Add nested group inside ${group}`,
  deleteGroupLabel: (group: string) => `Delete ${group} and every condition inside it`,
  deleteLeafLabel: (label: string, path: string) => `Delete ${label} condition ${path}`,
  leafTypeLabel: (path: string) => `Condition type for condition ${path}`,
  leafFieldLabel: (field: string, label: string, path: string) =>
    `${field} for ${label} condition ${path}`,
  fullscreen: "Fullscreen",
  fullscreenLabel: "Show the condition tree fullscreen",
  exitFullscreen: "Exit fullscreen (Esc)",
  exitFullscreenLabel: "Exit fullscreen, or press Escape",
};

interface ConditionFlowEditorProps {
  value: Record<string, unknown>;
  onChange?: (tree: Record<string, unknown>) => void;
  readOnly?: boolean;
}

/**
 * The achievement `condition_tree` editor: the shared rule builder wired to the
 * engine's registry.
 *
 * The node list comes from `achievements/rules/condition-types` rather than a
 * local copy, which drifted eight nodes behind the backend; `required`/
 * `optional` come from the same place the validator reads.
 */
export function ConditionFlowEditor({ value, onChange, readOnly }: Readonly<ConditionFlowEditorProps>) {
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  // The registry only changes when the engine ships a new node, so it is cached
  // for the session rather than refetched per editor mount.
  const { data: conditionTypes } = useQuery({
    queryKey: achievementQueryKeys.conditionTypes(workspaceId),
    queryFn: () => adminService.getConditionTypes(workspaceId!),
    enabled: !!workspaceId,
    staleTime: Infinity
  });

  // Sub-condition-only predicates (`player_role`, `player_div`) are rejected at
  // the top level by the validator, so they are not offered here.
  const leafOptions = useMemo(
    () =>
      (conditionTypes ?? [])
        .filter((option) => !option.subcondition_only)
        .map((option) => ({ value: option.name, label: conditionLabel(option.name) })),
    [conditionTypes]
  );

  const renderLeafFields = useCallback(
    ({ nodeId, leafType, params, setParam, controlName }: RuleLeafFieldsProps) => (
      <ConditionLeafFields
        nodeId={nodeId}
        conditionType={leafType}
        params={params}
        setParam={setParam}
        controlName={controlName}
      />
    ),
    []
  );

  return (
    <RuleBuilder
      value={value}
      onChange={onChange}
      readOnly={readOnly}
      leafOptions={leafOptions}
      defaultLeafType={DEFAULT_CONDITION_TYPE}
      palette={SIDEBAR_GROUPS}
      renderLeafFields={renderLeafFields}
      labelForLeaf={conditionLabel}
      summarizeLeaf={formatParamsSummary}
      labels={LABELS}
    />
  );
}
