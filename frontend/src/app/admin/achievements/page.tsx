"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Download,
  LibraryBig,
  Play,
  Plus,
  RotateCcw,
  Sprout,
  Upload,
  UserPlus,
} from "lucide-react";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { EvaluationRunSummary } from "@/components/admin/achievements/EvaluationRunSummary";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { Button } from "@/components/ui/button";
import { usePermissions } from "@/hooks/usePermissions";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { AchievementRule } from "@/types/admin.types";

import { AchievementFormDialog } from "./_components/AchievementFormDialog";
import { AchievementLibraryDialog } from "./_components/AchievementLibraryDialog";
import { AchievementOverrideDialog, type OverrideDraftState } from "./_components/AchievementOverrideDialog";
import { AchievementOverridesCard } from "./_components/AchievementOverridesCard";
import { AchievementsTable } from "./_components/AchievementsTable";
import { DryRunResultDialog } from "./_components/DryRunResultDialog";
import { EvaluateAchievementsDialog } from "./_components/EvaluateAchievementsDialog";
import { ImportErrorPanel, ImportResultPanel } from "./_components/ImportOutcomePanels";
import { useAchievementCatalog } from "./_hooks/useAchievementCatalog";
import { useAchievementRuleActions } from "./_hooks/useAchievementRuleActions";
import { useAchievementRuleForm } from "./_hooks/useAchievementRuleForm";

const emptyOverrideDraft: OverrideDraftState = { userName: "", action: "grant", reason: "" };

export default function AchievementsPage() {
  const router = useRouter();
  const { canAccessPermission } = usePermissions();
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);

  const [deletingRule, setDeletingRule] = useState<AchievementRule | null>(null);
  const [hardResetOpen, setHardResetOpen] = useState(false);
  const [libraryDialogOpen, setLibraryDialogOpen] = useState(false);

  const [evaluateDialogOpen, setEvaluateDialogOpen] = useState(false);
  const [evalTournamentId, setEvalTournamentId] = useState<number | undefined>(undefined);
  const [evalSelectedRuleIds, setEvalSelectedRuleIds] = useState<Set<number>>(new Set());

  const [overrideDialogOpen, setOverrideDialogOpen] = useState(false);
  const [overrideDraft, setOverrideDraft] = useState<OverrideDraftState>(emptyOverrideDraft);
  const [overrideFormError, setOverrideFormError] = useState<string | null>(null);
  const jsonInputRef = useRef<HTMLInputElement>(null);

  const canCreate = canAccessPermission("achievement.create", workspaceId);
  const canUpdate = canAccessPermission("achievement.update", workspaceId);
  const canDelete = canAccessPermission("achievement.delete", workspaceId);

  const { tournaments, overrides, refetchOverrides, allRules } = useAchievementCatalog({
    workspaceId,
    pickersOpen: evaluateDialogOpen || overrideDialogOpen,
  });

  const form = useAchievementRuleForm(workspaceId);

  const actions = useAchievementRuleActions({
    workspaceId,
    jsonInputRef,
    onDeleted: () => setDeletingRule(null),
    onEvaluated: () => setEvaluateDialogOpen(false),
    onOverrideSaved: () => {
      refetchOverrides();
      setOverrideDialogOpen(false);
      setOverrideDraft((prev) => ({ ...emptyOverrideDraft, action: prev.action }));
      setOverrideFormError(null);
    },
    onOverrideRemoved: () => refetchOverrides(),
  });

  // Validated on submit rather than by disabling the button, so the reader can
  // read what is missing instead of guessing why nothing happens.
  const handleOverrideSubmit = () => {
    const missing: string[] = [];
    if (!overrideDraft.userId) missing.push("a user");
    if (!overrideDraft.ruleId) missing.push("an achievement");
    if (!overrideDraft.reason.trim()) missing.push("a reason");
    if (missing.length > 0) {
      setOverrideFormError(`Pick ${missing.join(", ")} before saving the override.`);
      return;
    }
    setOverrideFormError(null);
    actions.overrideMutation.mutate({
      achievement_rule_id: overrideDraft.ruleId!,
      user_id: overrideDraft.userId!,
      tournament_id: overrideDraft.tournamentId ?? null,
      action: overrideDraft.action,
      reason: overrideDraft.reason,
    });
  };

  if (!workspaceId) {
    return (
      <div className="space-y-6">
        <AdminPageHeader
          title="Achievements"
          description="Condition-tree rules, evaluation runs and manual overrides."
        />
        <EmptyNote>
          Pick a workspace in the sidebar to load its achievement catalog.
        </EmptyNote>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <AdminPageHeader
        title="Achievements"
        description="Condition-tree rules, evaluation runs and manual overrides."
        actions={
          <div className="flex gap-2">
            <input
              ref={jsonInputRef}
              type="file"
              accept="application/json,.json"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void actions.importRulesFromFile(file);
              }}
            />
            <Button variant="outline" size="sm" onClick={() => void actions.exportRules()}>
              <Download className="mr-2 h-4 w-4" aria-hidden />
              Export JSON
            </Button>
            <Button variant="outline" size="sm" onClick={() => setLibraryDialogOpen(true)}>
              <LibraryBig className="mr-2 h-4 w-4" aria-hidden />
              Browse library
            </Button>
            {(canCreate || canUpdate) && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => jsonInputRef.current?.click()}
                disabled={actions.importMutation.isPending}
              >
                <Upload className={`mr-2 h-4 w-4 ${actions.importMutation.isPending ? "animate-spin" : ""}`} aria-hidden />
                Import JSON
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setEvalSelectedRuleIds(new Set());
                setEvalTournamentId(undefined);
                setEvaluateDialogOpen(true);
              }}
            >
              <Play className="mr-2 h-4 w-4" aria-hidden />
              Evaluate achievements
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                actions.overrideMutation.reset();
                setOverrideFormError(null);
                setOverrideDialogOpen(true);
              }}
            >
              <UserPlus className="mr-2 h-4 w-4" aria-hidden />
              Add manual override
            </Button>
            {canCreate && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => actions.seedMutation.mutate()}
                disabled={actions.seedMutation.isPending}
              >
                <Sprout className={`mr-2 h-4 w-4 ${actions.seedMutation.isPending ? "animate-spin" : ""}`} aria-hidden />
                Seed defaults
              </Button>
            )}
            {canCreate && (
              <Button
                variant="destructive"
                onClick={() => setHardResetOpen(true)}
                disabled={actions.hardResetMutation.isPending}
              >
                <RotateCcw className={`mr-2 h-4 w-4 ${actions.hardResetMutation.isPending ? "animate-spin" : ""}`} aria-hidden />
                Hard reset
              </Button>
            )}
            {canCreate && (
              <Button onClick={form.openCreate}>
                <Plus className="mr-2 h-4 w-4" aria-hidden />
                Create achievement
              </Button>
            )}
          </div>
        }
      />

      {actions.evaluationResult && (
        <EvaluationRunSummary
          run={actions.evaluationResult}
          onDismiss={actions.dismissEvaluationResult}
          tournamentName={
            tournaments?.results.find(
              (tournament) => tournament.id === actions.evaluationResult?.tournament_id,
            )?.name
          }
        />
      )}

      {actions.importError && (
        <ImportErrorPanel message={actions.importError} onDismiss={actions.dismissImportError} />
      )}

      {actions.importResult && (
        <ImportResultPanel result={actions.importResult} onDismiss={actions.dismissImportResult} />
      )}

      <AchievementsTable
        workspaceId={workspaceId}
        actions={{
          canUpdate,
          canDelete,
          onOpen: (rule) => router.push(`/admin/achievements/${rule.id}`),
          onEdit: form.openEdit,
          onTest: (rule) => actions.testMutation.mutate(rule.id),
          onEvaluate: (rule) => {
            setEvalSelectedRuleIds(new Set([rule.id]));
            setEvalTournamentId(undefined);
            setEvaluateDialogOpen(true);
          },
          onToggle: (rule) => actions.toggleMutation.mutate({ id: rule.id, enabled: !rule.enabled }),
          onDelete: setDeletingRule,
        }}
      />

      {overrides && overrides.length > 0 && (
        <AchievementOverridesCard
          overrides={overrides}
          rules={allRules}
          onDelete={(id) => actions.deleteOverrideMutation.mutate(id)}
          isDeleting={actions.deleteOverrideMutation.isPending}
        />
      )}

      <AchievementLibraryDialog
        open={libraryDialogOpen}
        onOpenChange={setLibraryDialogOpen}
        workspaceId={workspaceId}
        canImport={canCreate || canUpdate}
        onImported={actions.setImportResult}
      />

      <EvaluateAchievementsDialog
        open={evaluateDialogOpen}
        onOpenChange={setEvaluateDialogOpen}
        tournaments={tournaments?.results ?? []}
        rules={allRules ?? []}
        tournamentId={evalTournamentId}
        onTournamentChange={setEvalTournamentId}
        selectedRuleIds={evalSelectedRuleIds}
        onSelectedRuleIdsChange={setEvalSelectedRuleIds}
        onRun={() => actions.evaluate(evalTournamentId, evalSelectedRuleIds)}
        isRunning={actions.evaluateMutation.isPending}
      />

      <AchievementOverrideDialog
        open={overrideDialogOpen}
        onOpenChange={setOverrideDialogOpen}
        rules={allRules ?? []}
        tournaments={tournaments?.results ?? []}
        draft={overrideDraft}
        onDraftChange={setOverrideDraft}
        onSubmit={handleOverrideSubmit}
        isSaving={actions.overrideMutation.isPending}
        formError={overrideFormError}
        saveError={
          actions.overrideMutation.error instanceof Error
            ? actions.overrideMutation.error.message
            : undefined
        }
      />

      <AchievementFormDialog form={form} />

      {canDelete && deletingRule && (
        <ConfirmDialog
          open={!!deletingRule}
          onOpenChange={(open) => !open && setDeletingRule(null)}
          onConfirm={() => actions.deleteMutation.mutate(deletingRule.id)}
          pending={actions.deleteMutation.isPending}
          intent={{
            title: "Delete achievement",
            description: `“${deletingRule.name}” (${deletingRule.slug}) is removed from this workspace. Players keep nothing from it.`,
            confirmLabel: actions.deleteMutation.isPending ? "Deleting…" : "Delete",
            tone: "danger",
            cascade: [
              "Every evaluation result awarding this achievement",
              "Manual grant and revoke overrides referencing it",
            ],
          }}
        />
      )}

      {canCreate && (
        <ConfirmDialog
          open={hardResetOpen}
          onOpenChange={setHardResetOpen}
          onConfirm={() => {
            setHardResetOpen(false);
            actions.hardResetMutation.mutate();
          }}
          pending={actions.hardResetMutation.isPending}
          intent={{
            title: "Hard reset achievements",
            description:
              "The rule catalog for this workspace is replaced with the defaults, every current result is cleared, and a full re-evaluation runs immediately.",
            confirmLabel: actions.hardResetMutation.isPending ? "Resetting…" : "Hard reset",
            tone: "danger",
            cascade: ["Custom achievements that are not part of the default set"],
          }}
        />
      )}

      <DryRunResultDialog result={actions.testResult} onDismiss={actions.dismissTestResult} />
    </div>
  );
}
