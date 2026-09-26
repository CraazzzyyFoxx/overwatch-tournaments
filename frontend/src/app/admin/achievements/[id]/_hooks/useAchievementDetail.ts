"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { notifyEvaluationRun } from "@/components/admin/achievements/EvaluationRunSummary";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import tournamentService from "@/services/tournament.service";
import { achievementQueryKeys } from "@/lib/achievements/query-keys";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import type {
  AchievementOverrideCreateInput,
  AchievementRuleUpdateInput,
} from "@/types/admin.types";

/** How the users table is currently sliced. Every field is part of its query key. */
export interface RuleUsersView {
  tournamentId?: number;
  sort: string;
  order: "asc" | "desc";
}

/** One row of the "users who earned this" table. */
export interface RuleUserRow {
  user_id: number;
  user_name: string;
  count: number;
  last_tournament_id: number | null;
  last_match_id: number | null;
  first_qualified: string | null;
}

/** Everything one achievement's page reads: the rule, its users, its overrides. */
export function useAchievementDetailData({
  workspaceId,
  ruleId,
  usersView,
}: {
  workspaceId: number | null;
  ruleId: number;
  usersView: RuleUsersView;
}) {
  const { data: rule, isLoading } = useQuery({
    queryKey: achievementQueryKeys.rule(workspaceId, ruleId),
    queryFn: () => adminService.getAchievementRule(workspaceId!, ruleId),
    enabled: !!workspaceId
  });

  const { data: tournaments } = useQuery({
    queryKey: tournamentQueryKeys.list(),
    queryFn: () => tournamentService.getAll(null)
  });

  const users = useInfiniteQuery({
    queryKey: achievementQueryKeys.ruleUsersPage(
      workspaceId,
      ruleId,
      usersView.tournamentId,
      usersView.sort,
      usersView.order
    ),
    queryFn: ({ pageParam = 1 }) =>
      adminService.getAchievementRuleUsers(workspaceId!, ruleId, {
        page: pageParam,
        per_page: 30,
        tournament_id: usersView.tournamentId,
        sort: usersView.sort,
        order: usersView.order
      }),
    getNextPageParam: (lastPage) =>
      lastPage.total / lastPage.per_page > lastPage.page ? lastPage.page + 1 : undefined,
    enabled: !!workspaceId,
    initialPageParam: 1
  });

  const { data: overrides, refetch: refetchOverrides } = useQuery({
    queryKey: achievementQueryKeys.overrides(workspaceId, ruleId),
    queryFn: async () => {
      const all = await adminService.getAchievementOverrides(workspaceId!);
      return all.filter((o) => o.achievement_rule_id === ruleId);
    },
    enabled: !!workspaceId
  });

  return { rule, isLoading, tournaments, users, overrides, refetchOverrides };
}

/** Everything one achievement's page writes. */
export function useAchievementDetailMutations({
  workspaceId,
  ruleId,
  onUpdated,
  onTreeSaved,
  onOverrideSaved,
  onOverrideRemoved,
  onDeleted
}: {
  workspaceId: number | null;
  ruleId: number;
  onUpdated: () => void;
  onTreeSaved: () => void;
  onOverrideSaved: () => void;
  onOverrideRemoved: () => void;
  onDeleted: () => void;
}) {
  const queryClient = useQueryClient();
  const ruleKey = achievementQueryKeys.rule(workspaceId, ruleId);

  const updateMutation = useMutation({
    mutationFn: async ({
      data,
      imageFile
    }: {
      data: AchievementRuleUpdateInput;
      imageFile: File | null;
    }) => {
      const updated = await adminService.updateAchievementRule(workspaceId!, ruleId, data);
      // The badge is uploaded against the rule's slug, so it can only be
      // attached once the rule itself has been written.
      if (imageFile && updated.slug) {
        const uploadResult = await adminService.uploadAchievementImage(
          updated.slug,
          imageFile,
          workspaceId!
        );
        await adminService.updateAchievementRule(workspaceId!, ruleId, {
          image_url: uploadResult.public_url
        });
      }
      return updated;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ruleKey });
      queryClient.invalidateQueries({ queryKey: achievementQueryKeys.adminList(workspaceId) });
      onUpdated();
    }
  });

  const saveTreeMutation = useMutation({
    mutationFn: (conditionTree: Record<string, unknown>) =>
      adminService.updateAchievementRule(workspaceId!, ruleId, { condition_tree: conditionTree }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ruleKey });
      queryClient.invalidateQueries({ queryKey: achievementQueryKeys.adminList(workspaceId) });
      onTreeSaved();
    }
  });

  const deleteMutation = useMutation({
    mutationFn: () => adminService.deleteAchievementRule(workspaceId!, ruleId),
    onSuccess: onDeleted
  });

  const toggleMutation = useMutation({
    mutationFn: (enabled: boolean) =>
      adminService.updateAchievementRule(workspaceId!, ruleId, { enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ruleKey })
  });

  const evaluateMutation = useMutation({
    mutationFn: (tournamentId?: number) =>
      adminService.evaluateAchievements(workspaceId!, {
        tournament_id: tournamentId,
        rule_ids: [ruleId]
      }),
    onSuccess: (data) => {
      notifyEvaluationRun(data);
      queryClient.invalidateQueries({
        queryKey: achievementQueryKeys.ruleUsers(workspaceId, ruleId)
      });
    }
  });

  const testMutation = useMutation({
    mutationFn: (tournamentId?: number) =>
      adminService.testAchievementRule(workspaceId!, ruleId, tournamentId),
    onSuccess: (data) => {
      notify.success("Dry-run complete", {
        description: `${data.qualifying_count} users qualify`
      });
    }
  });

  const overrideMutation = useMutation({
    mutationFn: (draft: AchievementOverrideCreateInput) =>
      adminService.createAchievementOverride(workspaceId!, draft),
    onSuccess: onOverrideSaved
  });

  const deleteOverrideMutation = useMutation({
    mutationFn: (id: number) => adminService.deleteAchievementOverride(workspaceId!, id),
    onSuccess: onOverrideRemoved
  });

  return {
    updateMutation,
    saveTreeMutation,
    deleteMutation,
    toggleMutation,
    evaluateMutation,
    testMutation,
    overrideMutation,
    deleteOverrideMutation
  };
}
