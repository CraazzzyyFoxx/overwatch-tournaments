"use client";

import { Suspense, useEffect, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { HeroFrame } from "@/components/site/PageHero";
import AnalyticsPicker from "@/app/(site)/tournaments/analytics/components/AnalyticsPicker";
import TournamentHero from "@/app/(site)/tournaments/analytics/components/TournamentHero";
import { DisciplineWidget } from "@/disciplines/DisciplineWidget";
import { loadAnalyticsUI } from "@/disciplines/registry/analytics";
import type { AnalyticsHeroParts } from "@/disciplines/types";
import { useDisciplineMetadata, useDisciplines } from "@/hooks/useDisciplineMetadata";
import { useEntityWorkspace } from "@/hooks/useEntityWorkspace";
import { usePermissions } from "@/hooks/usePermissions";
import { getTournamentStatusMeta } from "@/lib/tournament/status";
import type { StatsScope } from "@/lib/site/stats-scope";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import tournamentService from "@/services/tournament.service";
import { useWorkspaceStore } from "@/stores/workspace.store";

function parseId(value: string | null): number | null {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

/**
 * The tournament analytics page (P7 §7 `analytics` slot host). The page owns what is game-neutral: the tournament
 * picker (the viewing scope's tournaments of games that declare analytics), the selected tournament as owner (its
 * workspace and game metadata, never the browsing filter), the viewer's analytics permissions and the page shell.
 * The board itself — rankings, forecasts, standings — is the tournament's game module's. A game without an analytics
 * capability gets an explicit unsupported state and no analytics read.
 */
const AnalyticsPage = ({ scope }: Readonly<{ scope: StatsScope }>) => {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { hasPermission, canAccessPermission } = usePermissions();
  const t = useTranslations();
  const currentWorkspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);

  const tournamentId = parseId(searchParams.get("tournamentId"));

  // Resolve the selected tournament's owner without changing the viewing filter.
  const ownerQuery = useQuery({
    queryKey: tournamentQueryKeys.overview(tournamentId),
    queryFn: () => tournamentService.getPublicOverview(tournamentId!),
    enabled: tournamentId != null,
    staleTime: 5 * 60_000
  });
  const owner = ownerQuery.data;
  const ownerWorkspaceId = owner?.workspace_id ?? null;
  useEntityWorkspace(ownerWorkspaceId, owner?.discipline);
  const metadataQuery = useDisciplineMetadata(ownerWorkspaceId ?? "all", owner?.discipline ?? null);
  const metadata = metadataQuery.data;

  // The picker follows the viewing filter; the selected event keeps its owner.
  const pickerWorkspaceId = scope === "all" ? "all" : currentWorkspaceId;
  const tournamentsQuery = useQuery({
    // Its own entry: the hero's stage progress reads the stages the other `byWorkspace` pickers do not load.
    queryKey: [...tournamentQueryKeys.byWorkspace(pickerWorkspaceId ?? "global"), "stages"],
    queryFn: () => tournamentService.getAll(null, pickerWorkspaceId, null, ["stages", "participants_count"])
  });
  const gamesQuery = useDisciplines(pickerWorkspaceId ?? "all");
  // Offered (and opened by default): tournaments of the scope's ENABLED games that have an analytics board. A
  // disabled game's historical tournaments stay reachable only as an explicitly opened owner (by URL).
  const analyticsGames = useMemo(
    () =>
      new Set(
        (gamesQuery.data ?? []).filter((game) => game.enabled && game.capabilities.analytics).map((game) => game.code)
      ),
    [gamesQuery.data]
  );
  const offered = useMemo(
    () => (tournamentsQuery.data?.results ?? []).filter((tournament) => analyticsGames.has(tournament.discipline)),
    [tournamentsQuery.data?.results, analyticsGames]
  );
  const tournaments = useMemo(
    () => (owner && !offered.some((item) => item.id === owner.id) ? [owner, ...offered] : offered),
    [offered, owner]
  );
  const activeTournament = tournaments.find((tournament) => tournament.id === tournamentId) ?? null;

  const listsReady = tournamentsQuery.isSuccess && gamesQuery.isSuccess;
  const firstOfferedId = offered[0]?.id ?? null;
  useEffect(() => {
    const next = new URLSearchParams(searchParams.toString());
    let changed = false;
    if (next.get("tab")) {
      next.delete("tab");
      changed = true;
    }
    if (tournamentId == null && listsReady && firstOfferedId !== null) {
      next.set("tournamentId", String(firstOfferedId));
      changed = true;
    }
    if (changed) router.replace(`${pathname}?${next.toString()}`);
  }, [pathname, router, searchParams, tournamentId, listsReady, firstOfferedId]);

  // Algorithm ids are global: a ranking picked for one tournament stays chosen for the next one when it has it
  // (the board replaces an id the new tournament's list does not offer).
  const pushTournamentId = (value: string) => {
    const next = new URLSearchParams(searchParams.toString());
    next.set("tournamentId", value);
    router.push(`${pathname}?${next.toString()}`);
  };

  const hero = (parts: AnalyticsHeroParts) =>
    // The pickers' tournament has not resolved yet: the header's real shape, not a "pick one" prompt that flashes.
    tournamentId != null && !activeTournament && !tournamentsQuery.isError && !gamesQuery.isError ? (
      <AnalyticsHeroSkeleton />
    ) : (
      <TournamentHero
        tournament={activeTournament}
        parts={parts}
        picker={
          <AnalyticsPicker
            tournaments={tournaments}
            tournamentId={tournamentId}
            loadingTournaments={tournamentsQuery.isPending || gamesQuery.isPending}
            isErrorTournaments={tournamentsQuery.isError || gamesQuery.isError}
            onTournamentChange={pushTournamentId}
            controls={parts.controls}
          />
        }
      />
    );

  const renderPage = () => {
    if (!listsReady && !tournamentsQuery.isError && !gamesQuery.isError) {
      return <AnalyticsContentSkeleton />;
    }
    if (tournamentId == null) {
      // A failed list is an error with a retry, never the "choose" empty state (DESIGN.md §9).
      if (tournamentsQuery.isError || gamesQuery.isError) {
        return (
          <PageStateCard
            state="error"
            title={t("analytics.briefing.errorTournaments")}
            onAction={() => {
              if (tournamentsQuery.isError) void tournamentsQuery.refetch();
              if (gamesQuery.isError) void gamesQuery.refetch();
            }}
          />
        );
      }
      return (
        <PageStateCard
          state="empty"
          title={t("analytics.page.chooseParams")}
          description={t("analytics.page.chooseParamsDesc")}
        />
      );
    }
    if (ownerQuery.isError || metadataQuery.isError) {
      return (
        <PageStateCard
          state="error"
          title={t("analytics.page.unavailable")}
          description={t("analytics.page.unavailableDesc")}
          onAction={() => void (ownerQuery.isError ? ownerQuery.refetch() : metadataQuery.refetch())}
        />
      );
    }
    if (!owner || !metadata) return <AnalyticsContentSkeleton />;
    if (!metadata.discipline.capabilities.analytics) {
      return (
        <PageStateCard
          state="empty"
          title={t("analytics.page.unsupported", { game: metadata.discipline.name })}
          description={t("analytics.page.unsupportedDesc")}
        />
      );
    }
    return null;
  };

  const blocked = renderPage();
  return (
    <div className="flex flex-col gap-6">
      {blocked !== null || !owner || !metadata ? (
        <>
          {hero({})}
          {blocked}
        </>
      ) : (
        <DisciplineWidget
          discipline={metadata.discipline.code}
          load={loadAnalyticsUI}
          slot="analytics"
          capabilities={metadata.discipline.capabilities}
          requires="analytics"
          props={{
            tournamentId: owner.id,
            workspaceId: owner.workspace_id,
            metadata,
            // v2 ML reads (performance, Monte-Carlo distribution, match quality, SHAP) are permission-gated
            // server-side; gating the board's fetches keeps the public baseline from firing a 403.
            canReadV2: canAccessPermission("analytics.read", owner.workspace_id),
            canUpdate: hasPermission("analytics.update"),
            ended: getTournamentStatusMeta(owner.status).isEnded,
            hero
          }}
          fallback={null}
          pending={
            <>
              {hero({})}
              <AnalyticsContentSkeleton />
            </>
          }
        />
      )}
    </div>
  );
};

/** The board's first paint: its toolbar row, then the standings list beside the team panel. */
const AnalyticsContentSkeleton = () => (
  <div className="flex flex-col gap-4">
    <div className="flex items-center justify-between gap-2">
      <Skeleton className="h-8 w-72 max-w-full rounded-lg" />
      <Skeleton className="h-8 w-28 rounded-lg" />
    </div>
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(21rem,1fr)]">
      <div className="space-y-px overflow-hidden rounded-xl border border-[color:var(--aqt-border)]">
        {Array.from({ length: 8 }).map((_, index) => (
          <Skeleton key={index} className="h-[3.75rem] rounded-none" />
        ))}
      </div>
      <Skeleton className="hidden h-[26rem] rounded-xl lg:block" />
    </div>
  </div>
);

/** The hero's frame and columns while the tournament resolves. */
const AnalyticsHeroSkeleton = () => (
  <HeroFrame>
    <div className="grid gap-8 px-6 py-8 md:px-10 md:py-9 lg:grid-cols-[1.5fr_1fr] lg:items-end lg:gap-12">
      <div className="space-y-4">
        <Skeleton className="h-3 w-52" />
        <Skeleton className="h-12 w-full max-w-2xl" />
        <Skeleton className="h-4 w-64" />
        <Skeleton className="h-10 w-full max-w-[30rem]" />
      </div>
      <div className="flex flex-col gap-6">
        <div className="grid grid-cols-2 gap-x-7 gap-y-5 sm:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-14" />
          ))}
        </div>
        <Skeleton className="h-8 w-full max-w-[27.5rem]" />
      </div>
    </div>
  </HeroFrame>
);

const AnalyticsPageFallback = () => (
  <div className="flex flex-col gap-6">
    <AnalyticsHeroSkeleton />
    <AnalyticsContentSkeleton />
  </div>
);

const AnalyticsClient = ({ scope }: Readonly<{ scope: StatsScope }>) => (
  <Suspense fallback={<AnalyticsPageFallback />}>
    <AnalyticsPage scope={scope} />
  </Suspense>
);

export default AnalyticsClient;
