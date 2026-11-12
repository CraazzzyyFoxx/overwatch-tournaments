"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { ConfirmDialog } from "@craazzzyyfoxx/admin-kit/kit/ConfirmDialog";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { EntityWorkspace } from "@/components/workspace/EntityWorkspace";
import { usePermissions } from "@/hooks/usePermissions";
import { useWorkspaceStore } from "@/stores/workspace.store";

import { AchievementFormDialog } from "../_components/AchievementFormDialog";
import { AchievementOverridesCard } from "../_components/AchievementOverridesCard";
import { useAchievementRuleForm } from "../_hooks/useAchievementRuleForm";
import { AchievementDetailHeader } from "./_components/AchievementDetailHeader";
import { AchievementDetailsCard } from "./_components/AchievementDetailsCard";
import { AchievementUsersTable } from "./_components/AchievementUsersTable";
import { ConditionTreeCard } from "./_components/ConditionTreeCard";
import { RuleOverrideDialog, type RuleOverrideDraft } from "./_components/RuleOverrideDialog";
import { useAchievementDetailData, useAchievementDetailMutations } from "./_hooks/useAchievementDetail";

const emptyOverrideDraft: RuleOverrideDraft = { userName: "", action: "grant", reason: "" };

export default function AchievementDetailPage() {
  const t = useTranslations("adminAchievements");
  const params = useParams();
  const router = useRouter();
  const { canAccessPermission } = usePermissions();
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const ruleId = Number(params.id);

  const canUpdate = canAccessPermission("achievement.update", workspaceId);
  const canDelete = canAccessPermission("achievement.delete", workspaceId);

  const [deletingRule, setDeletingRule] = useState(false);
  const [editingTree, setEditingTree] = useState(false);
  const [overrideDialogOpen, setOverrideDialogOpen] = useState(false);
  const [overrideDraft, setOverrideDraft] = useState<RuleOverrideDraft>(emptyOverrideDraft);

  const { rule, isLoading, isError, refetch, tournaments, overrides, refetchOverrides } =
    useAchievementDetailData({ workspaceId, ruleId });

  const form = useAchievementRuleForm(workspaceId, rule?.discipline ?? null);

  const {
    saveTreeMutation,
    deleteMutation,
    toggleMutation,
    evaluateMutation,
    testMutation,
    overrideMutation,
    deleteOverrideMutation,
  } = useAchievementDetailMutations({
    workspaceId,
    ruleId,
    discipline: rule?.discipline,
    onTreeSaved: () => setEditingTree(false),
    onOverrideSaved: () => {
      refetchOverrides();
      setOverrideDialogOpen(false);
      setOverrideDraft((prev) => ({ ...emptyOverrideDraft, action: prev.action }));
    },
    onOverrideRemoved: () => refetchOverrides(),
    onDeleted: () => router.push("/admin/achievements"),
  });

  if (!workspaceId) {
    return <PageStateCard state="empty" headingLevel={1} title={t("detail.selectWorkspace")} />;
  }

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-32 w-full rounded-xl" />
        <Skeleton className="h-75 w-full rounded-xl" />
      </div>
    );
  }

  if (isError) {
    return <PageStateCard state="error" headingLevel={1} onAction={() => refetch()} />;
  }

  if (!rule) {
    return <PageStateCard state="not-found" headingLevel={1} title={t("detail.notFound")} />;
  }

  return (
    <div className="space-y-6">
      {/* The rule's community while it is open, which need not be the one the shell had. */}
      <EntityWorkspace workspaceId={rule.workspace_id} />
      <AchievementDetailHeader
        rule={rule}
        canUpdate={canUpdate}
        canDelete={canDelete}
        isTesting={testMutation.isPending}
        isEvaluating={evaluateMutation.isPending}
        onTest={() => testMutation.mutate(undefined)}
        onEvaluate={() => evaluateMutation.mutate(undefined)}
        onToggle={() => toggleMutation.mutate(!rule.enabled)}
        onEdit={() => form.openEdit(rule)}
        onDelete={() => setDeletingRule(true)}
      />

      {/* Cards stack at the settings hub's spacing; the header keeps its own air. */}
      <div className="space-y-4">
        <AchievementDetailsCard
          rule={rule}
          minTournamentName={tournaments.find((tournament) => tournament.id === rule.min_tournament_id)?.name}
        />

        <ConditionTreeCard
          conditionTree={rule.condition_tree as Record<string, unknown>}
          discipline={rule.discipline}
          canUpdate={canUpdate}
          editing={editingTree}
          onEditingChange={setEditingTree}
          onSave={(tree) => saveTreeMutation.mutate(tree)}
          isSaving={saveTreeMutation.isPending}
          saveError={
            saveTreeMutation.error instanceof Error ? saveTreeMutation.error.message : undefined
          }
        />

        <AchievementUsersTable
          workspaceId={workspaceId}
          ruleId={ruleId}
          tournaments={tournaments}
          onAddOverride={() => {
            overrideMutation.reset();
            setOverrideDialogOpen(true);
          }}
        />

        {overrides && overrides.length > 0 && (
          <AchievementOverridesCard
            overrides={overrides}
            tournaments={tournaments}
            onDelete={(id) => deleteOverrideMutation.mutate(id)}
            isDeleting={deleteOverrideMutation.isPending}
          />
        )}
      </div>

      <RuleOverrideDialog
        open={overrideDialogOpen}
        onOpenChange={setOverrideDialogOpen}
        ruleId={ruleId}
        ruleName={rule.name}
        tournaments={tournaments}
        draft={overrideDraft}
        onDraftChange={setOverrideDraft}
        onSubmit={(input) => overrideMutation.mutate(input)}
        isSaving={overrideMutation.isPending}
        saveError={overrideMutation.error instanceof Error ? overrideMutation.error.message : undefined}
      />

      <AchievementFormDialog form={form} />

      <ConfirmDialog
        open={deletingRule}
        onOpenChange={setDeletingRule}
        onConfirm={() => deleteMutation.mutate()}
        pending={deleteMutation.isPending}
        intent={{
          title: t("detail.deleteTitle", { slug: rule.slug }),
          description: t("detail.deleteDescription"),
          confirmLabel: deleteMutation.isPending ? t("common.deleting") : t("common.delete"),
          tone: "danger",
          cascade: [t("list.deleteCascadeResult")],
        }}
      />
    </div>
  );
}
