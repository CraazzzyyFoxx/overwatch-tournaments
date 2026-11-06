"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { notifyEvaluationRun } from "@/components/admin/achievements/EvaluationRunSummary";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import tournamentService from "@/services/tournament.service";
import { achievementQueryKeys } from "@/lib/achievements/query-keys";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import type { AchievementOverrideCreateInput } from "@/types/admin.types";

/** One row of the "users who earned this" table. */
export interface RuleUserRow {
  user_id: number;
  user_name: string;
  count: number;
  last_tournament_id: number | null;
  last_match_id: number | null;
  first_qualified: string | null;
}

/** What one achievement's page reads besides its users table: the rule, the tournaments, its overrides. */
export function useAchievementDetailData({
  workspaceId,
  ruleId,
}: {
  workspaceId: number | null;
  ruleId: number;
}) {
  const { data: rule, isLoading, isError, refetch } = useQuery({
    queryKey: achievementQueryKeys.rule(workspaceId, ruleId),
    queryFn: () => adminService.getAchievementRule(workspaceId!, ruleId),
    enabled: !!workspaceId
  });

  const { data: tournaments } = useQuery({
    queryKey: tournamentQueryKeys.list(),
    queryFn: () => tournamentService.getAll()
  });

  // The overrides list is per game, and which game is the loaded rule's: its id key
  // (workspace + rule) names exactly one game, so the read waits for the rule.
  const discipline = rule?.discipline;
  const { data: overrides, refetch: refetchOverrides } = useQuery({
    queryKey: achievementQueryKeys.overrides(workspaceId, ruleId),
    queryFn: async () => {
      const all = await adminService.getAchievementOverrides(workspaceId!, discipline!);
      return all.filter((o) => o.achievement_rule_id === ruleId);
    },
    enabled: !!workspaceId && !!discipline
  });

  return {
    rule,
    isLoading,
    isError,
    refetch,
    // Only the rule's own game's tournaments can be picked or named on its page.
    tournaments: (tournaments?.results ?? []).filter((tournament) => tournament.discipline === discipline),
    overrides,
    refetchOverrides
  };
}

/** Everything one achievement's page writes, except the metadata edit (the shared rule form owns it). */
export function useAchievementDetailMutations({
  workspaceId,
  ruleId,
  discipline,
  onTreeSaved,
  onOverrideSaved,
  onOverrideRemoved,
  onDeleted
}: {
  workspaceId: number | null;
  ruleId: number;
  /** The rule's own game; `undefined` until the rule has loaded (no mutation can run before). */
  discipline: string | undefined;
  onTreeSaved: () => void;
  onOverrideSaved: () => void;
  onOverrideRemoved: () => void;
  onDeleted: () => void;
}) {
  const t = useTranslations("adminAchievements");
  const queryClient = useQueryClient();
  const ruleKey = achievementQueryKeys.rule(workspaceId, ruleId);

  // The rule is on its game's list and on the all-games list: stale every game's rule list of the workspace (R17).
  const invalidateLists = () => {
    queryClient.invalidateQueries({ queryKey: achievementQueryKeys.adminListsOf(workspaceId) });
    queryClient.invalidateQueries({ queryKey: achievementQueryKeys.publicLists() });
  };

  const saveTreeMutation = useMutation({
    mutationFn: (conditionTree: Record<string, unknown>) =>
      adminService.updateAchievementRule(workspaceId!, ruleId, { condition_tree: conditionTree }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ruleKey });
      invalidateLists();
      onTreeSaved();
    }
  });

  const deleteMutation = useMutation({
    mutationFn: () => adminService.deleteAchievementRule(workspaceId!, ruleId),
    onSuccess: () => {
      invalidateLists();
      onDeleted();
    }
  });

  const toggleMutation = useMutation({
    mutationFn: (enabled: boolean) =>
      adminService.updateAchievementRule(workspaceId!, ruleId, { enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ruleKey });
      invalidateLists();
    }
  });

  const evaluateMutation = useMutation({
    mutationFn: (tournamentId?: number) =>
      adminService.evaluateAchievements(workspaceId!, discipline!, {
        tournament_id: tournamentId,
        rule_ids: [ruleId]
      }),
    onSuccess: (data) => {
      notifyEvaluationRun(data, t as unknown as Parameters<typeof notifyEvaluationRun>[1]);
      queryClient.invalidateQueries({
        queryKey: achievementQueryKeys.ruleUsers(workspaceId, ruleId)
      });
    }
  });

  const testMutation = useMutation({
    mutationFn: (tournamentId?: number) =>
      adminService.testAchievementRule(workspaceId!, ruleId, tournamentId),
    onSuccess: (data) => {
        notify.success(t("dryRun.complete"), {
          description: t("dryRun.qualifying", { count: data.qualifying_count })
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
    saveTreeMutation,
    deleteMutation,
    toggleMutation,
    evaluateMutation,
    testMutation,
    overrideMutation,
    deleteOverrideMutation
  };
}
