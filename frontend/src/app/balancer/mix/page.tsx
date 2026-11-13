"use client";

import { useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useDebounce } from "use-debounce";

import { PickupCreateMixDialog } from "@/app/balancer/mix/PickupCreateMixDialog";
import { PickupLeaderboard, PickupRatingTable } from "@/app/balancer/mix/PickupLeaderboard";
import { ActiveMixes, MixHistory } from "@/app/balancer/mix/PickupMixList";
import { OPEN_MIXES } from "@/app/balancer/mix/pickup-chrome";
import {
  LEADERBOARD_MIN_GAMES,
  mergeMixStats,
  sinceFor,
  type StatsPeriodKey
} from "@/app/balancer/mix/pickup-stats";
import { useMixHistory } from "@/app/balancer/mix/useMixHistory";
import { LinkTabs } from "@/components/kit/LinkTabs";
import { HeroCoord, HeroStat, PageHero } from "@/components/site/PageHero";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Dialog } from "@craazzzyyfoxx/admin-kit/ui/dialog";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { GameScopeControl } from "@/components/workspace/GameScopeControl";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useGameDescriptors } from "@/hooks/useGameDescriptors";
import { useGameScope } from "@/hooks/useGameScope";
import { usePermissions } from "@/hooks/usePermissions";
import { useFormatter } from "@/lib/datetime/client";
import { notify } from "@/lib/notify";
import { showsGameMarks } from "@/lib/site/discipline-scope";
import { customGameKeys, customGameService } from "@/services/custom-game.service";
import { useWorkspaceStore } from "@/stores/workspace.store";

/**
 * The mixes hub: what is running now, every finished mix by month, and who is
 * winning -- the entry point for hosting one. Opening or starting a mix both
 * leave this page for `/balancer/mix/[gameId]`.
 *
 * A multi page (spec §5): every game under "all games", one game under a game (`?discipline=` or the scope), and
 * under the "all communities" scope every community in the public directory or the viewer's own, where each one is
 * read on its own and the results are joined here (history by id, the scoreboard by player). An invalid or empty game
 * resolution makes no request.
 * `?view=rating` swaps the directory for the full scoreboard.
 */
export default function BalancerPickupListPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const t = useTranslations("mixes");
  const format = useFormatter();
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const statsScope = useWorkspaceStore((state) => state.statsScope);
  const hostWorkspaceId = useWorkspaceStore((state) => state.hostLockedWorkspaceId);
  const workspaces = useWorkspaceStore((state) => state.workspaces);
  const workspacesLoading = useWorkspaceStore((state) => state.isLoading);
  const all = statsScope === "all" && hostWorkspaceId == null;
  const profile = useAuthProfile().user;
  const memberOf = new Set(profile?.workspaces.map((membership) => membership.workspace_id));
  // Every community is read on its own, so "all" must stay small: the directory (backend `_is_listed`) plus the
  // viewer's own -- which is the switcher list itself for everyone but a superuser, whose list is every workspace.
  // ponytail: O(listed + own) requests per panel; a cross-workspace list/stats read makes it O(1) if the directory grows.
  const visibleWorkspaces = workspaces.filter((workspace) =>
    all
      ? (!workspace.is_hidden && workspace.verification_status !== "unverified") || memberOf.has(workspace.id)
      : workspace.id === (hostWorkspaceId ?? workspaceId)
  );
  const workspaceIds = visibleWorkspaces.map((workspace) => workspace.id);
  const gameScope = useGameScope();
  const resolution = gameScope.resolution;
  // `null` = every game. Only a game narrows the directory; invalid/empty resolutions never reach a request.
  const discipline = gameScope.game;
  const browsable = resolution?.game.kind === "all" || resolution?.game.kind === "game";
  const descriptors = useGameDescriptors();
  const gameMarks =
    resolution !== null && showsGameMarks(resolution, gameScope.games ?? []) ? descriptors : undefined;
  // Under "all communities" every row and card names its community; one community is said once, in the hero.
  const communities = all ? new Map(visibleWorkspaces.map((workspace) => [workspace.id, workspace])) : undefined;
  const ontology =
    useDisciplineMetadata(all ? "all" : (hostWorkspaceId ?? workspaceId ?? "all"), discipline).data ?? null;
  const { canAccessPermission } = usePermissions();
  const creationWorkspaces = visibleWorkspaces.filter(
    (workspace) =>
      canAccessPermission("custom_game.create", workspace.id) &&
      (discipline === null ? workspace.disciplines_enabled.length > 0 : workspace.disciplines_enabled.includes(discipline))
  );
  const canEdit = creationWorkspaces.length > 0;
  const [createOpen, setCreateOpen] = useState(false);
  const view = searchParams.get("view") === "rating" ? "rating" : "mixes";
  const viewerIds = profile?.linkedPlayers.map((player) => player.playerId) ?? [];
  const pending = workspacesLoading || resolution === null;

  const openQueries = useQueries({
    queries: visibleWorkspaces.map((workspace) => ({
      queryKey: customGameKeys.list(workspace.id, discipline, OPEN_MIXES),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        customGameService.list(workspace.id, discipline, OPEN_MIXES, { signal }),
      enabled: browsable,
    })),
  });
  const openGames = openQueries.flatMap((query) => query.data?.items ?? []).sort((a, b) => b.id - a.id);

  const [search, setSearch] = useState("");
  const [query] = useDebounce(search.trim(), 300);
  const history = useMixHistory({ workspaceIds, discipline, q: query, enabled: browsable });

  const [period, setPeriod] = useState<StatsPeriodKey>("all");
  // Pinned to the period, not recomputed per render: a `since` that drifted
  // with the clock would be a new query key every render.
  const since = useMemo(() => sinceFor(period, new Date()), [period]);
  // The hero always counts all time; the scoreboard follows the period (the same request when it is all time).
  const totalsQueries = useQueries({
    queries: visibleWorkspaces.map((workspace) => ({
      queryKey: customGameKeys.stats(workspace.id, null, discipline ?? undefined),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        customGameService.stats(workspace.id, null, discipline ?? undefined, { signal }),
      enabled: browsable,
      staleTime: 60_000,
    })),
  });
  const boardQueries = useQueries({
    queries: visibleWorkspaces.map((workspace) => ({
      queryKey: customGameKeys.stats(workspace.id, since, discipline ?? undefined),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        customGameService.stats(workspace.id, since, discipline ?? undefined, { signal }),
      enabled: browsable,
      staleTime: 60_000,
    })),
  });

  const totalsReady = totalsQueries.length > 0 && totalsQueries.every((query) => query.data !== undefined);
  const totals = totalsReady
    ? {
        mixes: totalsQueries.reduce((sum, query) => sum + (query.data?.mixes ?? 0), 0),
        matches: totalsQueries.reduce((sum, query) => sum + (query.data?.matches ?? 0), 0),
        players: mergeMixStats(
          totalsQueries.map((query, index) => ({ workspaceId: workspaceIds[index], stats: query.data! }))
        ).length,
      }
    : null;
  const boardReady = boardQueries.length > 0 && boardQueries.every((query) => query.data !== undefined);
  const rated = boardReady
    ? mergeMixStats(boardQueries.map((query, index) => ({ workspaceId: workspaceIds[index], stats: query.data! })))
    : [];
  const ranked = rated.filter((player) => player.games >= LEADERBOARD_MIN_GAMES);
  const viewer = rated.find((player) => player.playerId !== null && viewerIds.includes(player.playerId)) ?? null;
  const board = {
    ranked,
    viewer,
    loading: pending || (!boardReady && !boardQueries.some((query) => query.isError)),
    error: boardQueries.some((query) => query.isError),
    onRetry: () => {
      for (const query of boardQueries) if (query.isError) void query.refetch();
    },
    period,
    onPeriodChange: setPeriod,
    allCommunities: all && visibleWorkspaces.length > 1,
    ontology: discipline === null ? null : ontology,
  };

  const viewHref = (next: "mixes" | "rating") => {
    const params = new URLSearchParams(searchParams.toString());
    if (next === "rating") params.set("view", "rating");
    else params.delete("view");
    const rest = params.toString();
    return rest ? `/balancer/mix?${rest}` : "/balancer/mix";
  };

  // A copy starts from a mix already on screen: the open ones and the history pages loaded so far.
  const loadedGames = [...openGames, ...history.items];
  const createGame = useMutation({
    mutationFn: (input: { workspaceId: number; discipline: string; name: string; cloneFromGameId: number | null }) => {
      if (!creationWorkspaces.some((workspace) => workspace.id === input.workspaceId)) {
        throw new Error(t("create.workspaceRequired"));
      }
      if (input.cloneFromGameId != null && !loadedGames.some((game) =>
        game.id === input.cloneFromGameId && game.workspace_id === input.workspaceId && game.discipline === input.discipline
      )) {
        throw new Error(t("create.sourceRequired"));
      }
      return customGameService.create(input.workspaceId, input.discipline, input.name, input.cloneFromGameId);
    },
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: customGameKeys.lists(created.workspace_id) });
      router.push(`/balancer/mix/${created.id}`);
    },
    onError: (error) => notify.apiError(error)
  });

  if (!all && workspaceId == null && hostWorkspaceId == null) {
    return (
      <div className="flex flex-1 items-center justify-center py-12">
        <PageStateCard
          state="empty"
          headingLevel={1}
          title={t("chooseWorkspace")}
          description={t("workspaceHint")}
          className="w-full max-w-md"
        />
      </div>
    );
  }

  const statValue = (value: number | undefined) =>
    value === undefined ? <Skeleton className="h-8 w-14 motion-reduce:animate-none" /> : format.number(value);
  const totalsFailed = totalsQueries.some((query) => query.isError);
  const openLoading = pending || openQueries.some((query) => query.isLoading);

  return (
    <div className="flex w-full min-w-0 flex-col gap-6">
      <PageHero
        eyebrow={!all && visibleWorkspaces[0] ? <HeroCoord>{visibleWorkspaces[0].name}</HeroCoord> : null}
        title={t("title")}
        lede={t("description")}
        actions={
          canEdit && browsable ? (
            <Button size="lg" className="px-5" onClick={() => setCreateOpen(true)}>
              <Plus className="size-4" aria-hidden="true" />
              {t("createAction")}
            </Button>
          ) : null
        }
        aside={
          browsable && !totalsFailed ? (
            <div className="flex flex-wrap gap-x-10 gap-y-5 lg:justify-end">
              <HeroStat label={t("hero.mixes")} value={statValue(totals?.mixes)} />
              <HeroStat label={t("hero.matches")} value={statValue(totals?.matches)} />
              <HeroStat label={t("hero.players")} value={statValue(totals?.players)} />
            </div>
          ) : null
        }
      />

      {resolution && !browsable ? (
        <GameScopeControl scope={gameScope} variant="multi" />
      ) : (
        <>
          <LinkTabs
            ariaLabel={t("views.label")}
            activeKey={view}
            items={[
              { key: "mixes", label: t("views.mixes"), href: viewHref("mixes") },
              { key: "rating", label: t("views.rating"), href: viewHref("rating") },
            ]}
          />
          {view === "rating" ? (
            <PickupRatingTable {...board} />
          ) : (
            <div className="grid w-full min-w-0 grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_22rem] xl:items-start 2xl:grid-cols-[minmax(0,1fr)_26rem]">
              <div className="flex min-w-0 flex-col gap-8">
                <ActiveMixes
                  games={openGames}
                  loading={openLoading}
                  error={openQueries.some((query) => query.isError)}
                  onRetry={() => {
                    for (const query of openQueries) if (query.isError) void query.refetch();
                  }}
                  communities={communities}
                  gameMarks={gameMarks}
                />
                <MixHistory
                  items={history.items}
                  loading={pending || history.loading}
                  updating={history.updating}
                  error={gameScope.isError || history.error}
                  onRetry={() => {
                    if (gameScope.isError) gameScope.refetch();
                    history.retry();
                  }}
                  hasMore={history.hasMore}
                  loadingMore={history.loadingMore}
                  onLoadMore={history.loadMore}
                  search={search}
                  onSearchChange={setSearch}
                  query={query}
                  nothingYet={!openLoading && openGames.length === 0}
                  canEdit={canEdit}
                  onCreateGame={() => setCreateOpen(true)}
                  communities={communities}
                  gameMarks={gameMarks}
                />
              </div>
              <aside className="min-w-0 xl:sticky xl:top-24">
                <PickupLeaderboard {...board} fullHref={viewHref("rating")} />
              </aside>
            </div>
          )}
        </>
      )}

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        {createOpen && gameScope.games ? (
          <PickupCreateMixDialog
            games={loadedGames}
            workspaces={creationWorkspaces}
            disciplines={gameScope.games}
            fixedDiscipline={discipline}
            scopedWorkspaceId={all ? null : (hostWorkspaceId ?? workspaceId)}
            creating={createGame.isPending}
            onCreate={async (name, cloneFromGameId, creationWorkspaceId, creationDiscipline) => {
              await createGame.mutateAsync({
                workspaceId: creationWorkspaceId,
                discipline: creationDiscipline,
                name,
                cloneFromGameId
              });
            }}
            onClose={() => setCreateOpen(false)}
          />
        ) : null}
      </Dialog>
    </div>
  );
}
