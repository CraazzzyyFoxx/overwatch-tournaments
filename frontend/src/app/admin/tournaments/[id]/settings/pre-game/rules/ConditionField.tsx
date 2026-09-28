"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Filter, RotateCcw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { RuleBuilder, LOGICAL_COLORS, type RuleLeafFieldsProps, type RulePaletteGroup } from "@/components/rule-builder";
import type {
  PickBanCondition,
  PickBanConditionContext,
  PickBanKind,
  PickBanLeafSpec,
  PickBanRulesCatalog,
} from "@/types/tournament.types";

import type { CatalogueItem } from "../CataloguePicker";
import { ParamFields } from "./ParamFields";

/**
 * One condition tree of the ruleset, edited in the shared rule builder.
 *
 * Shown collapsed as a chip — "anything", or the leaves it names — because a
 * phase board with three React Flow canvases per column would be unreadable and
 * would mount a canvas for every condition nobody is editing.
 */
export function ConditionField({
  label,
  description,
  value,
  context,
  kind,
  catalog,
  catalogue,
  /** Only a step with a target may use `target_role_match`. */
  hasTarget,
  disabled,
  onChange,
}: Readonly<{
  label: string;
  description: string;
  value: PickBanCondition;
  context: PickBanConditionContext;
  kind: PickBanKind;
  catalog: PickBanRulesCatalog | undefined;
  catalogue: CatalogueItem[];
  hasTarget?: boolean;
  disabled?: boolean;
  onChange: (next: PickBanCondition) => void;
}>) {
  const t = useTranslations("pickBan.rules");
  const [open, setOpen] = useState(false);

  const leaves = useMemo(
    () =>
      (catalog?.leaves ?? []).filter(
        (leaf) =>
          leaf.contexts.includes(context) &&
          leaf.kinds.includes(kind) &&
          (hasTarget === true || !leaf.requires_target)
      ),
    [catalog, context, kind, hasTarget]
  );
  const groups = useMemo(() => catalog?.groups?.[kind] ?? [], [catalog, kind]);

  const leafLabel = useCallback(
    (type: string | undefined) => {
      if (!type) return t("leafUnknown");
      const key = `leaf.${type}` as "leaf.map_index";
      return t.has(key) ? t(key) : type;
    },
    [t]
  );

  const summarize = useCallback(
    (_type: string, params: Record<string, unknown>) =>
      Object.entries(params)
        .filter(([, paramValue]) => paramValue != null && paramValue !== "")
        .map(([key, paramValue]) =>
          `${key}: ${Array.isArray(paramValue) ? paramValue.join(", ") : String(paramValue)}`
        )
        .join(", "),
    []
  );

  const specByType = useMemo(() => {
    const table: Record<string, PickBanLeafSpec> = {};
    for (const leaf of leaves) table[leaf.type] = leaf;
    return table;
  }, [leaves]);

  const renderLeafFields = useCallback(
    ({ leafType, params, setParam, controlName }: RuleLeafFieldsProps) => (
      <ParamFields
        specs={leafType == null ? [] : specByType[leafType]?.params ?? []}
        params={params}
        setParam={setParam}
        controlName={controlName}
        kind={kind}
        groups={groups}
        catalogue={catalogue}
        disabled={disabled}
      />
    ),
    [specByType, kind, groups, catalogue, disabled]
  );

  const palette = useMemo<RulePaletteGroup[]>(
    () => [
      {
        label: t("builder.logicGroup"),
        items: [
          { type: "logical", logicalOp: "AND", label: "AND", color: LOGICAL_COLORS.AND },
          { type: "logical", logicalOp: "OR", label: "OR", color: LOGICAL_COLORS.OR },
          { type: "logical", logicalOp: "NOT", label: "NOT", color: LOGICAL_COLORS.NOT },
        ],
      },
      {
        label: t("builder.leafGroup"),
        items: leaves.map((leaf) => ({
          type: "leaf" as const,
          leafType: leaf.type,
          label: leafLabel(leaf.type),
        })),
      },
    ],
    [leaves, leafLabel, t]
  );

  const labels = useMemo(
    () => ({
      outlineTitle: t("builder.outlineTitle"),
      outlineGroup: (path: string, op: string) => t("builder.outlineGroup", { path, op }),
      paletteSearchPlaceholder: t("builder.searchPlaceholder"),
      paletteSearchLabel: t("builder.searchLabel"),
      paletteHint: t("builder.paletteHint"),
      paletteEmpty: (query: string) => t("builder.paletteEmpty", { query }),
      paletteAdd: (item: string) => t("builder.paletteAdd", { item }),
      groupName: (path: string) => t("builder.groupName", { path }),
      operatorLabel: (group: string) => t("builder.operatorLabel", { group }),
      addLeaf: t("builder.addLeaf"),
      addLeafLabel: (group: string) => t("builder.addLeafLabel", { group }),
      addGroup: t("builder.addGroup"),
      addGroupLabel: (group: string) => t("builder.addGroupLabel", { group }),
      deleteGroupLabel: (group: string) => t("builder.deleteGroupLabel", { group }),
      deleteLeafLabel: (leaf: string, path: string) =>
        t("builder.deleteLeafLabel", { leaf, path }),
      leafTypeLabel: (path: string) => t("builder.leafTypeLabel", { path }),
      leafFieldLabel: (field: string, leaf: string, path: string) =>
        t("builder.leafFieldLabel", { field, leaf, path }),
      fullscreen: t("builder.fullscreen"),
      fullscreenLabel: t("builder.fullscreenLabel"),
      exitFullscreen: t("builder.exitFullscreen"),
      exitFullscreenLabel: t("builder.exitFullscreenLabel"),
    }),
    [t]
  );

  const summary = conditionSummary(value, leafLabel, t("anything"));

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-7 max-w-full gap-1.5 border-dashed text-xs font-normal"
        onClick={() => setOpen(true)}
      >
        <Filter aria-hidden className="size-3.5 shrink-0" />
        <span className="text-muted-foreground">{label}</span>
        <span className="truncate">{summary}</span>
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-5xl">
          <DialogHeader>
            <DialogTitle>{label}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>

          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{t(`context.${context}`)}</Badge>
            {leaves.length === 0 ? (
              <span className="text-xs text-muted-foreground">{t("builder.noLeaves")}</span>
            ) : null}
            <div className="flex-1" />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={disabled}
              onClick={() => onChange({})}
            >
              <RotateCcw aria-hidden className="me-2 size-3.5" />
              {t("clearCondition")}
            </Button>
          </div>

          <RuleBuilder
            value={value}
            readOnly={disabled}
            onChange={(tree) => onChange(tree as PickBanCondition)}
            leafOptions={leaves.map((leaf) => ({ value: leaf.type, label: leafLabel(leaf.type) }))}
            defaultLeafType={leaves[0]?.type ?? "item_group"}
            palette={palette}
            renderLeafFields={renderLeafFields}
            labelForLeaf={leafLabel}
            summarizeLeaf={summarize}
            labels={labels}
          />
        </DialogContent>
      </Dialog>
    </>
  );
}

/** "anything", one leaf's name, or "N conditions" — enough for a chip. */
function conditionSummary(
  condition: PickBanCondition,
  leafLabel: (type: string | undefined) => string,
  anything: string
): string {
  const names: string[] = [];
  const walk = (node: PickBanCondition, negated: boolean) => {
    if (node == null || Object.keys(node).length === 0) return;
    if ("AND" in node) return (node.AND as PickBanCondition[]).forEach((child) => walk(child, negated));
    if ("OR" in node) return (node.OR as PickBanCondition[]).forEach((child) => walk(child, negated));
    if ("NOT" in node) return walk(node.NOT as PickBanCondition, !negated);
    const label = leafLabel((node as { type: string }).type);
    names.push(negated ? `¬${label}` : label);
  };
  walk(condition, false);
  return names.length === 0 ? anything : names.join(" · ");
}
