"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { PickupLeaderboard } from "@/app/balancer/pickup/PickupLeaderboard";
import { PickupMixList } from "@/app/balancer/pickup/PickupMixList";
import {
  LEADERBOARD_MIN_GAMES,
  leaderboardRows,
  sinceFor,
  type StatsPeriodKey,
} from "@/app/balancer/pickup/pickup-stats";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import { customGameKeys, customGameService } from "@/services/custom-game.service";
import { useWorkspaceStore } from "@/stores/workspace.store";

/**
 * Every mix a workspace has run, newest first — the entry point for hosting
 * one. Opening or starting a mix both leave this page for
 * `/balancer/pickup/[gameId]`, which reads and edits the one already picked.
 */
export default function BalancerPickupListPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const { canAccessPermission } = usePermissions();
  // The mix-hosting grant, not a tournament permission: a workspace member can
  // run a pickup game without holding admin rights over teams.
  const canEdit = workspaceId != null && canAccessPermission("custom_game.create", workspaceId);

  const gamesQuery = useQuery({
    queryKey: customGameKeys.list(workspaceId ?? 0),
    queryFn: () => customGameService.list(workspaceId as number),
    enabled: workspaceId != null,
  });

  const [period, setPeriod] = useState<StatsPeriodKey>("all");
  // Pinned to the period, not recomputed per render: a `since` that drifted
  // with the clock would be a new query key every render.
  const since = useMemo(() => sinceFor(period, new Date()), [period]);
  const statsQuery = useQuery({
    queryKey: customGameKeys.stats(workspaceId ?? 0, since),
    queryFn: () => customGameService.stats(workspaceId as number, since),
    enabled: workspaceId != null,
    staleTime: 60_000,
  });

  const createGame = useMutation({
    mutationFn: (input: { name: string; cloneFromGameId: number | null }) =>
      customGameService.create(workspaceId as number, input.name, input.cloneFromGameId),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: customGameKeys.list(workspaceId as number) });
      router.push(`/balancer/pickup/${created.id}`);
    },
    onError: (error) => notify.apiError(error),
  });

  if (workspaceId == null) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
        Pick a workspace in the top bar to open mixes.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5 xl:flex-row xl:items-start">
      <div className="min-w-0 flex-1">
        <PickupMixList
          canEdit={canEdit}
          games={gamesQuery.data ?? []}
          loading={gamesQuery.isLoading}
          error={gamesQuery.isError}
          onRetry={() => void gamesQuery.refetch()}
          creating={createGame.isPending}
          onCreateGame={(name, cloneFromGameId) => createGame.mutate({ name, cloneFromGameId })}
        />
      </div>
      <div className="xl:w-[420px] xl:shrink-0">
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
  );
}
