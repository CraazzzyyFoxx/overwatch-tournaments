"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { Skeleton } from "@/components/ui/skeleton";
import { hasUnsavedChanges } from "@/lib/form-change";
import { usePermissions } from "@/hooks/usePermissions";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { AchievementRuleUpdateInput } from "@/types/admin.types";

import { achievementFormData } from "../achievement-form.model";
import { AchievementDetailHeader } from "./_components/AchievementDetailHeader";
import { AchievementDetailsCard } from "./_components/AchievementDetailsCard";
import { AchievementEditDialog } from "./_components/AchievementEditDialog";
import { AchievementUsersCard } from "./_components/AchievementUsersCard";
import { ConditionTreeCard } from "./_components/ConditionTreeCard";
import { RuleOverrideDialog, type RuleOverrideDraft } from "./_components/RuleOverrideDialog";
import { RuleOverridesCard } from "./_components/RuleOverridesCard";
import {
  useAchievementDetailData,
  useAchievementDetailMutations,
  type RuleUsersView,
} from "./_hooks/useAchievementDetail";

const emptyOverrideDraft: RuleOverrideDraft = { userName: "", action: "grant", reason: "" };

export default function AchievementDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { canAccessPermission } = usePermissions();
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const ruleId = Number(params.id);

  const canUpdate = canAccessPermission("achievement.update", workspaceId);
  const canDelete = canAccessPermission("achievement.delete", workspaceId);

  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [deletingRule, setDeletingRule] = useState(false);
  const [editingTree, setEditingTree] = useState(false);
  const [overrideDialogOpen, setOverrideDialogOpen] = useState(false);
  const [overrideDraft, setOverrideDraft] = useState<RuleOverrideDraft>(emptyOverrideDraft);
  const [formData, setFormData] = useState<AchievementRuleUpdateInput>({});
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [usersView, setUsersView] = useState<RuleUsersView>({ sort: "count", order: "desc" });

  const { rule, isLoading, tournaments, users, overrides, refetchOverrides } =
    useAchievementDetailData({ workspaceId, ruleId, usersView });

  const {
    updateMutation,
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
    onUpdated: () => {
      setEditDialogOpen(false);
      setImageFile(null);
      setImagePreview(null);
    },
    onTreeSaved: () => setEditingTree(false),
    onOverrideSaved: () => {
      refetchOverrides();
      setOverrideDialogOpen(false);
      setOverrideDraft((prev) => ({ ...emptyOverrideDraft, action: prev.action }));
    },
    onOverrideRemoved: () => refetchOverrides(),
    onDeleted: () => router.push("/admin/achievements"),
  });

  const totalUsers = users.data?.pages[0]?.total ?? 0;

  if (!workspaceId) {
    return <div className="p-6 text-muted-foreground">Select a workspace first.</div>;
  }

  if (isLoading) {
    return (
      <div className="space-y-6 p-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (!rule) {
    return <div className="p-6 text-muted-foreground">Achievement not found.</div>;
  }

  return (
    <div className="space-y-6">
      <AchievementDetailHeader
        rule={rule}
        canUpdate={canUpdate}
        canDelete={canDelete}
        isEvaluating={evaluateMutation.isPending}
        onTest={() => testMutation.mutate(undefined)}
        onEvaluate={() => evaluateMutation.mutate(undefined)}
        onToggle={() => toggleMutation.mutate(!rule.enabled)}
        onEdit={() => {
          setFormData(achievementFormData(rule));
          updateMutation.reset();
          setEditDialogOpen(true);
        }}
        onDelete={() => setDeletingRule(true)}
      />

      <div className="grid grid-cols-1 gap-6">
        <AchievementDetailsCard rule={rule} totalUsers={totalUsers} />
      </div>

      <ConditionTreeCard
        conditionTree={rule.condition_tree as Record<string, unknown>}
        canUpdate={canUpdate}
        editing={editingTree}
        onEditingChange={setEditingTree}
        onSave={(tree) => saveTreeMutation.mutate(tree)}
        isSaving={saveTreeMutation.isPending}
        saveError={
          saveTreeMutation.error instanceof Error ? saveTreeMutation.error.message : undefined
        }
      />

      <AchievementUsersCard
        pages={users.data?.pages ?? []}
        totalUsers={totalUsers}
        tournaments={tournaments?.results ?? []}
        view={usersView}
        onViewChange={setUsersView}
        onAddOverride={() => {
          overrideMutation.reset();
          setOverrideDialogOpen(true);
        }}
        hasNextPage={users.hasNextPage}
        isFetchingNextPage={users.isFetchingNextPage}
        fetchNextPage={users.fetchNextPage}
        isError={users.isError}
      />

      {overrides && overrides.length > 0 && (
        <RuleOverridesCard
          overrides={overrides}
          onDelete={(id) => deleteOverrideMutation.mutate(id)}
        />
      )}

      <RuleOverrideDialog
        open={overrideDialogOpen}
        onOpenChange={setOverrideDialogOpen}
        ruleName={rule.name}
        tournaments={tournaments?.results ?? []}
        draft={overrideDraft}
        onDraftChange={setOverrideDraft}
        onSubmit={() =>
          overrideMutation.mutate({
            achievement_rule_id: ruleId,
            user_id: overrideDraft.userId!,
            tournament_id: overrideDraft.tournamentId ?? null,
            action: overrideDraft.action,
            reason: overrideDraft.reason,
          })
        }
        isSaving={overrideMutation.isPending}
        saveError={
          overrideMutation.error instanceof Error ? overrideMutation.error.message : undefined
        }
      />

      <AchievementEditDialog
        open={editDialogOpen}
        onOpenChange={(open) => {
          if (!open) setEditDialogOpen(false);
        }}
        slug={rule.slug}
        formData={formData}
        onFormDataChange={setFormData}
        imagePreview={imagePreview}
        onPickImage={(file) => {
          setImageFile(file);
          setImagePreview(URL.createObjectURL(file));
        }}
        onClearImage={() => {
          setImageFile(null);
          setImagePreview(null);
        }}
        onSubmit={() => updateMutation.mutate({ data: formData, imageFile })}
        isSubmitting={updateMutation.isPending}
        isDirty={editDialogOpen && hasUnsavedChanges(formData, achievementFormData(rule))}
        errorMessage={
          updateMutation.error instanceof Error ? updateMutation.error.message : undefined
        }
      />

      <ConfirmDialog
        open={deletingRule}
        onOpenChange={setDeletingRule}
        onConfirm={() => deleteMutation.mutate()}
        pending={deleteMutation.isPending}
        intent={{
          title: `Delete achievement "${rule.slug}"`,
          description:
            "The record and its linked data are removed permanently. This cannot be undone.",
          confirmLabel: deleteMutation.isPending ? "Deleting…" : "Delete",
          tone: "danger",
          cascade: ["Every evaluation result and manual override for this achievement"],
        }}
      />
    </div>
  );
}
