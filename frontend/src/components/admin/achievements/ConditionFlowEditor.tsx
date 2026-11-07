"use client";

import { useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { GraphCanvasSkeleton } from "@/components/graph-canvas/GraphCanvasSkeleton";
import { RuleBuilder, type RuleLeafFieldsProps } from "@/components/rule-builder";
import { PageStateCard } from "@/components/ui/page-state-card";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { achievementQueryKeys } from "@/lib/achievements/query-keys";
import { DEFAULT_CONDITION_TYPE, useConditionText } from "@/lib/achievements/condition-text";

import { ConditionLeafFields } from "./ConditionLeafFields";
import { createSidebarGroups, defaultLeafOf, filterPaletteByConditions } from "./condition-flow.model";

interface ConditionFlowEditorProps {
  value: Record<string, unknown>;
  onChange?: (tree: Record<string, unknown>) => void;
  readOnly?: boolean;
  /**
   * The game whose engine registry offers the nodes: the rule's own (immutable) or
   * the form's. It keys the metadata request, so one game's registry can never
   * answer for another's — not even a late response to a request made before the
   * game changed.
   */
  discipline: string;
}

/**
 * The achievement `condition_tree` editor: the shared rule builder wired to the
 * engine's registry.
 *
 * The node list comes from `achievements/rules/condition-types` for the editor's
 * `discipline` rather than a local copy, which drifted eight nodes behind the
 * backend; `required`/`optional` come from the same place the validator reads.
 * Both the palette and the leaf selector are cut down to what that registry
 * returned, and a game that returns nothing gets an explicit unavailable state:
 * no canvas, no addition, and never a node borrowed from another game.
 */
export function ConditionFlowEditor({ value, onChange, readOnly, discipline }: Readonly<ConditionFlowEditorProps>) {
  const t = useTranslations("adminAchievements");
  const tPalette = useTranslations("adminAchievements.palette");
  // Role names resolve in the rule's own workspace (the admin's current one), so its child roles are named.
  const ruleWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const { leafLabel, leafLine } = useConditionText(value, discipline, ruleWorkspaceId ?? "all");
  const labels = useMemo(() => ({
    outlineTitle: t("condition.treeOutline"),
    outlineGroup: (path: string, op: string) =>
      t("condition.outlineGroup", { path, operator: op }),
    groupName: (path: string) => t("condition.group", { path }),
    operatorLabel: (group: string) => t("condition.operatorFor", { group }),
    addLeaf: t("condition.addCondition"),
    addLeafLabel: (group: string) => t("condition.addInside", { group }),
    addGroup: t("condition.addGroup"),
    addGroupLabel: (group: string) => t("condition.addNested", { group }),
    deleteGroupLabel: (group: string) => t("condition.deleteGroup", { group }),
    deleteLeafLabel: (label: string, path: string) => t("condition.deleteCondition", { label, path }),
    leafTypeLabel: (path: string) => t("condition.typeFor", { path }),
    leafFieldLabel: (field: string, label: string, path: string) => t("condition.fieldFor", { field, label, path }),
  }), [t]);
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const emptyTree = Object.keys(value).length === 0;
  // Reading an existing tree needs no registry: its nodes name themselves. Only an
  // empty tree has to wait for it, because an empty tree draws as a node of the
  // game's default type and a game without one has nothing to draw. So a viewer
  // of a stored tree never asks — a game without conditions has no registry to ask.
  const needsRegistry = !readOnly || emptyTree;
  // The registry only changes when the engine ships a new node, so it is cached
  // for the session per game rather than refetched per editor mount.
  const { data: conditionTypes, isPending, isError, refetch } = useQuery({
    queryKey: achievementQueryKeys.conditionTypes(workspaceId, discipline),
    queryFn: () => adminService.getConditionTypes(workspaceId!, discipline),
    enabled: !!workspaceId && needsRegistry,
    staleTime: Infinity
  });

  // Sub-condition-only predicates (`player_role`, `player_div`) are rejected at
  // the top level by the validator, so they are not offered here.
  const offered = useMemo(
    () => (conditionTypes ?? []).filter((option) => !option.subcondition_only).map((option) => option.name),
    [conditionTypes]
  );
  const leafOptions = useMemo(
    () => offered.map((name) => ({ value: name, label: leafLabel(name) })),
    [offered, leafLabel]
  );
  // Palette entries live under `palette`; the operators and two shared words ("position", "record") under `condition`.
  const paletteText = useCallback(
    (key: string) => (tPalette.has(key as "logic") ? tPalette(key as "logic") : t(`condition.${key}` as "condition.logicalAnd")),
    [t, tPalette]
  );
  const palette = useMemo(
    () =>
      filterPaletteByConditions(createSidebarGroups(paletteText), new Set(offered), {
        label: tPalette("other"),
        labelFor: leafLabel,
      }),
    [paletteText, tPalette, offered, leafLabel]
  );
  const defaultLeaf = defaultLeafOf(offered, DEFAULT_CONDITION_TYPE);

  const renderLeafFields = useCallback(
    ({ leafType, params, setParam, controlName }: RuleLeafFieldsProps) => (
      <ConditionLeafFields
        conditionType={leafType}
        params={params}
        setParam={setParam}
        controlName={controlName}
      />
    ),
    []
  );

  const heightClass = readOnly ? "h-75" : "h-125";
  if (needsRegistry && isPending) {
    return (
      <div role="status" aria-busy="true" aria-label={t("condition.loadingTypes")}>
        <GraphCanvasSkeleton heightClass={heightClass} />
      </div>
    );
  }
  if (needsRegistry && isError) {
    return <PageStateCard state="error" description={t("condition.typesFailed")} onAction={() => refetch()} />;
  }
  if (needsRegistry && defaultLeaf === null) {
    return <PageStateCard state="empty" description={t("condition.unavailable")} />;
  }

  const builderDefault = defaultLeaf ?? DEFAULT_CONDITION_TYPE;
  return readOnly ? (
    <RuleBuilder
      value={value}
      readOnly
      defaultLeafType={builderDefault}
      labelForLeaf={leafLabel}
      summarizeLeaf={leafLine}
      labels={labels}
      heightClass={heightClass}
    />
  ) : (
    <RuleBuilder
      value={value}
      onChange={onChange}
      leafOptions={leafOptions}
      defaultLeafType={builderDefault}
      palette={palette}
      renderLeafFields={renderLeafFields}
      labelForLeaf={leafLabel}
      summarizeLeaf={leafLine}
      labels={labels}
      heightClass={heightClass}
    />
  );
}
