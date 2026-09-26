"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { Pencil } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

// @xyflow/react (plus its stylesheet) is the heaviest thing this route can
// pull, and the tree is one card on a page that is mostly forms and tables —
// so it loads on demand. Two entry points because the two call sites settle at
// different heights (`h-125` editing, `h-75` read-only) and a placeholder that
// lies about its height is a layout shift.
const ConditionFlowEditor = dynamic(
  () => import("@/components/admin/achievements/ConditionFlowEditor").then((m) => m.ConditionFlowEditor),
  { ssr: false, loading: () => <Skeleton className="h-125 w-full rounded-lg" /> }
);
const ConditionFlowViewer = dynamic(
  () => import("@/components/admin/achievements/ConditionFlowEditor").then((m) => m.ConditionFlowEditor),
  { ssr: false, loading: () => <Skeleton className="h-75 w-full rounded-lg" /> }
);

/**
 * The rule's evaluation logic, read-only until edited. The draft lives here and
 * is only handed back on save, so abandoning an edit costs nothing. Edit mode
 * itself is the page's, because it is the save mutation that ends it.
 */
export function ConditionTreeCard({
  conditionTree,
  canUpdate,
  editing,
  onEditingChange,
  onSave,
  isSaving,
  saveError
}: Readonly<{
  conditionTree: Record<string, unknown>;
  canUpdate: boolean;
  editing: boolean;
  onEditingChange: (editing: boolean) => void;
  onSave: (tree: Record<string, unknown>) => void;
  isSaving: boolean;
  saveError?: string;
}>) {
  const [draft, setDraft] = useState<Record<string, unknown>>({});

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle>Condition Tree</CardTitle>
          <CardDescription>
            {editing
              ? "Edit the evaluation logic"
              : "Visual representation of the evaluation logic"}
          </CardDescription>
        </div>
        {canUpdate && !editing && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setDraft(conditionTree);
              onEditingChange(true);
            }}
          >
            <Pencil className="mr-2 h-4 w-4" />
            Edit Tree
          </Button>
        )}
      </CardHeader>
      <CardContent>
        {editing ? (
          <div className="space-y-4">
            <ConditionFlowEditor value={draft} onChange={setDraft} />
            <div className="flex items-center justify-end gap-2 pt-2 border-t">
              {saveError && <p className="text-sm text-destructive mr-auto">{saveError}</p>}
              <Button variant="outline" onClick={() => onEditingChange(false)} disabled={isSaving}>
                Cancel
              </Button>
              <Button onClick={() => onSave(draft)} disabled={isSaving}>
                {isSaving ? "Saving…" : "Save condition tree"}
              </Button>
            </div>
          </div>
        ) : (
          <ConditionFlowViewer value={conditionTree} readOnly />
        )}
      </CardContent>
    </Card>
  );
}
