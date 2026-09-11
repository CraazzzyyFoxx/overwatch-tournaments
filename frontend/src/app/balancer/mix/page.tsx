"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { PickupCreateMixDialog } from "@/app/balancer/mix/PickupCreateMixDialog";
import { PickupLeaderboard } from "@/app/balancer/mix/PickupLeaderboard";
import { PickupMixList } from "@/app/balancer/mix/PickupMixList";
import {
  LEADERBOARD_MIN_GAMES,
  leaderboardRows,
  sinceFor,
  type StatsPeriodKey
} from "@/app/balancer/mix/pickup-stats";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { PageStateCard } from "@/components/ui/page-state-card";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import { customGameKeys, customGameService } from "@/services/custom-game.service";
import { useWorkspaceStore } from "@/stores/workspace.store";

/**
 * Every mix a workspace has run, newest first — the entry point for hosting
 * one. Opening or starting a mix both leave this page for
 * `/balancer/mix/[gameId]`, which reads and edits the one already picked.
 */
export default function BalancerPickupListPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const t = useTranslations("mixes");
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const { canAccessPermission } = usePermissions();
  // The mix-hosting grant, not a tournament permission: a workspace member can
  // run a pickup game without holding admin rights over teams.
  const canEdit = workspaceId != null && canAccessPermission("custom_game.create", workspaceId);

  const [createOpen, setCreateOpen] = useState(false);

  const gamesQuery = useQuery({
    queryKey: customGameKeys.list(workspaceId ?? 0),
    queryFn: () => customGameService.list(workspaceId as number),
    enabled: workspaceId != null
  });

  const [period, setPeriod] = useState<StatsPeriodKey>("all");
  // Pinned to the period, not recomputed per render: a `since` that drifted
  // with the clock would be a new query key every render.
  const since = useMemo(() => sinceFor(period, new Date()), [period]);
  const statsQuery = useQuery({
    queryKey: customGameKeys.stats(workspaceId ?? 0, since),
    queryFn: () => customGameService.stats(workspaceId as number, since),
    enabled: workspaceId != null,
    staleTime: 60_000
  });

  const createGame = useMutation({
    mutationFn: (input: { name: string; cloneFromGameId: number | null }) =>
      customGameService.create(workspaceId as number, input.name, input.cloneFromGameId),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: customGameKeys.list(workspaceId as number) });
      router.push(`/balancer/mix/${created.id}`);
    },
    onError: (error) => notify.apiError(error)
  });

  if (workspaceId == null) {
    return (
      <div className="flex flex-1 items-center justify-center py-12">
        <PageStateCard
          state="empty"
          title={t("chooseWorkspace")}
          description={t("workspaceHint")}
          className="w-full max-w-md"
        />
      </div>
    );
  }

  return (
    <div className="flex w-full min-w-0 flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <h1 className="font-display text-title font-semibold text-[color:var(--aqt-fg)]">
            {t("title")}
          </h1>
          <p className="text-body text-[color:var(--aqt-fg-muted)]">{t("description")}</p>
        </div>
        {canEdit ? (
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="size-4" aria-hidden="true" />
            {t("createAction")}
          </Button>
        ) : null}
      </div>

      <div className="grid w-full min-w-0 grid-cols-1 gap-6 xl:grid-cols-[1fr_380px] xl:items-start">
        <div className="min-w-0 w-full">
          <PickupMixList
            canEdit={canEdit}
            games={gamesQuery.data ?? []}
            loading={gamesQuery.isLoading}
            error={gamesQuery.isError}
            onRetry={() => void gamesQuery.refetch()}
            onCreateGame={() => setCreateOpen(true)}
          />
        </div>
        <div className="min-w-0 w-full">
          <PickupLeaderboard
            members={leaderboardRows(statsQuery.data?.members ?? [], LEADERBOARD_MIN_GAMES)}
            loading={statsQuery.isLoading}
            error={statsQuery.isError}
            onRetry={() => void statsQuery.refetch()}
            period={period}
            onPeriodChange={setPeriod}
          />
        </div>
      </div>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        {createOpen ? (
          <PickupCreateMixDialog
            games={gamesQuery.data ?? []}
            creating={createGame.isPending}
            onCreate={async (name, cloneFromGameId) => {
              await createGame.mutateAsync({ name, cloneFromGameId });
            }}
            onClose={() => setCreateOpen(false)}
          />
        ) : null}
      </Dialog>
    </div>
  );
}
