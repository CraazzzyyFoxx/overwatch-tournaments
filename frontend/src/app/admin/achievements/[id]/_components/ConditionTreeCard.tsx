"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import dynamic from "next/dynamic";

import { GraphCanvasSkeleton } from "@/components/graph-canvas/GraphCanvasSkeleton";
import { LoadErrorNote } from "@craazzzyyfoxx/admin-kit/kit/EmptyNote";
import { SettingGroup } from "@/components/kit/SettingRow";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Spinner } from "@craazzzyyfoxx/admin-kit/ui/spinner";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";

// @xyflow/react (plus its stylesheet) is the heaviest thing this route can
// pull, and the tree is one card on a page that is mostly forms and tables —
// so it loads on demand. Two entry points because the two call sites settle at
// different heights (`h-125` editing, `h-75` read-only) and a placeholder that
// lies about its height is a layout shift.
const ConditionFlowEditor = dynamic(
  () => import("@/components/admin/achievements/ConditionFlowEditor").then((m) => m.ConditionFlowEditor),
  { ssr: false, loading: () => <GraphCanvasSkeleton heightClass="h-125" /> }
);
const ConditionFlowViewer = dynamic(
  () => import("@/components/admin/achievements/ConditionFlowEditor").then((m) => m.ConditionFlowEditor),
  { ssr: false, loading: () => <GraphCanvasSkeleton heightClass="h-75" /> }
);

/**
 * The rule's evaluation logic, read-only until edited. The draft lives here and
 * is only handed back on save, so abandoning an edit costs nothing. Edit mode
 * itself is the page's, because it is the save mutation that ends it.
 */
export function ConditionTreeCard({
  conditionTree,
  discipline,
  canUpdate,
  editing,
  onEditingChange,
  onSave,
  isSaving,
  saveError
}: Readonly<{
  conditionTree: Record<string, unknown>;
  /** The rule's own game (immutable): it decides which conditions the editor offers. */
  discipline: string;
  canUpdate: boolean;
  editing: boolean;
  onEditingChange: (editing: boolean) => void;
  onSave: (tree: Record<string, unknown>) => void;
  isSaving: boolean;
  saveError?: string;
}>) {
  const t = useTranslations("adminAchievements");
  const tCommon = useTranslations("common");
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  // The condition vocabulary is the game module's; a game that declares none has nothing to edit with, and no
  // registry to ask. Unknown until its metadata loads, so the editor waits for an explicit yes and nothing that
  // could ask for a registry mounts before the answer.
  const metadata = useDisciplineMetadata("all", discipline);
  const conditions = metadata.data?.discipline.capabilities.achievement_conditions;
  // A stored tree draws itself without the registry; an empty one would need it, so it is only drawn for a game
  // known to have conditions.
  const showStored = conditions === true || Object.keys(conditionTree).length > 0;

  return (
    <SettingGroup
      id="conditions"
      title={t("detail.conditionTree")}
      actions={
        canUpdate && !editing && conditions === true ? (
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setDraft(conditionTree);
              onEditingChange(true);
            }}
          >
            {t("detail.editTree")}
          </Button>
        ) : null
      }
    >
      <div className="space-y-3">
        {conditions === false ? (
          <p className="text-sm text-muted-foreground">{tCommon("discipline.widgetUnsupported")}</p>
        ) : null}
        {editing ? (
          <div className="space-y-4">
            <ConditionFlowEditor value={draft} onChange={setDraft} discipline={discipline} />
            <div className="flex items-center justify-end gap-2 pt-2 border-t">
              {saveError && <p className="text-sm text-destructive mr-auto">{saveError}</p>}
              <Button variant="outline" onClick={() => onEditingChange(false)} disabled={isSaving}>
                {t("detail.cancelEdit")}
              </Button>
              <Button onClick={() => onSave(draft)} disabled={isSaving}>
                {isSaving && <Spinner />}
                {isSaving ? t("common.saving") : t("detail.saveTree")}
              </Button>
            </div>
          </div>
        ) : metadata.isPending ? (
          <GraphCanvasSkeleton heightClass="h-75" />
        ) : showStored ? (
          <ConditionFlowViewer value={conditionTree} readOnly discipline={discipline} />
        ) : metadata.isError ? (
          // Whether this game has conditions is unknown, and an empty tree would have to ask the registry.
          <LoadErrorNote onRetry={() => void metadata.refetch()} />
        ) : null}
      </div>
    </SettingGroup>
  );
}
