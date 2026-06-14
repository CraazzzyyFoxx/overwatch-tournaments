"use client";

import React, { Suspense, useCallback, useEffect, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import AnalyticsBriefing from "@/app/(site)/tournaments/analytics/components/AnalyticsBriefing";
import OrganizerTools from "@/app/(site)/tournaments/analytics/components/OrganizerTools";
import AttentionTriage from "@/app/(site)/tournaments/analytics/components/AttentionTriage";
import AnalyticsStandings from "@/app/(site)/tournaments/analytics/components/AnalyticsStandings";
import DeepDiveSection from "@/app/(site)/tournaments/analytics/components/DeepDiveSection";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";
import {
  canShowAnalyticsAdminToolbar,
  getPreferredAnalyticsAlgorithmId,
  sortAnalyticsAlgorithms
} from "@/app/(site)/tournaments/analytics/analytics.helpers";
import { usePermissions } from "@/hooks/usePermissions";
import { useTranslation } from "@/i18n/LanguageContext";
import tournamentService from "@/services/tournament.service";
import analyticsService from "@/services/analytics.service";
import { useWorkspaceStore } from "@/stores/workspace.store";

const AnalyticsPage = () => {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { hasPermission } = usePermissions();
  const { t } = useTranslation();
  const currentWorkspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);

  const parseId = useCallback((value: string | null) => {
    if (!value) return null;
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) return null;
    return parsed;
  }, []);

  const tournamentId = useMemo(() => parseId(searchParams.get("tournamentId")), [parseId, searchParams]);
  const algorithmId = useMemo(() => parseId(searchParams.get("algorithm")), [parseId, searchParams]);

  const {
    data: tournamentsData,
    isSuccess: isSuccessTournaments,
    isLoading: loadingTournaments,
    isError: isErrorTournaments
  } = useQuery({
    queryKey: ["tournaments", currentWorkspaceId ?? "global"],
    queryFn: () => tournamentService.getAll(null, currentWorkspaceId)
  });

  const {
    data: algorithmData,
    isSuccess: isSuccessAlgorithm,
    isLoading: loadingAlgorithms,
    isError: isErrorAlgorithms
  } = useQuery({
    // Keyed by tournament so each list carries `has_data` for that tournament,
    // letting the default prefer "OpenSkill + ML" only when it is populated.
    // Keep the previous list while refetching on a tournament switch so the
    // algorithm stays "known" (no stale-id analytics flash before has_data lands).
    queryKey: ["analytics", "algorithms", tournamentId],
    queryFn: () => analyticsService.getAlgorithms(tournamentId),
    placeholderData: (previousData) => previousData
  });

  const availableAlgorithms = useMemo(
    () => sortAnalyticsAlgorithms(algorithmData?.results ?? []),
    [algorithmData?.results]
  );
  const isKnownAlgorithmId =
    algorithmId != null && availableAlgorithms.some((algorithm) => algorithm.id === algorithmId);
  const canQueryAnalytics =
    tournamentId != null && algorithmId != null && (!isSuccessAlgorithm || isKnownAlgorithmId);
  const canRecalculateAnalytics = canShowAnalyticsAdminToolbar(hasPermission("analytics.update"));

  const {
    data: analytics,
    isLoading: loadingAnalytics,
    isError: isErrorAnalytics
  } = useQuery({
    queryKey: ["analytics", currentWorkspaceId ?? "global", tournamentId, algorithmId],
    queryFn: () => analyticsService.getAnalytics(tournamentId!, algorithmId!, currentWorkspaceId),
    enabled: canQueryAnalytics
  });

  const {
    data: performanceRows
  } = useQuery({
    queryKey: ["analytics", "performance-v2", tournamentId],
    queryFn: () => analyticsService.getPerformanceV2(tournamentId!),
    enabled: tournamentId != null
  });

  const performanceByPlayer = useMemo(
    () =>
      new Map(
        (performanceRows ?? []).map((row) => [row.player_id, row])
      ),
    [performanceRows]
  );

  // Monte Carlo standings distribution — same query key as
  // StandingsDistributionCard so react-query serves both from one request.
  const { data: standingsRows } = useQuery({
    queryKey: ["analytics-standings-distribution", tournamentId, undefined],
    queryFn: () => analyticsService.getStandingsDistribution(tournamentId!),
    enabled: tournamentId != null,
    staleTime: 60_000
  });

  const distributionByTeam = useMemo(
    () => new Map((standingsRows ?? []).map((row) => [row.team_id, row])),
    [standingsRows]
  );

  // Players the model expects to change division — drives the briefing verdict.
  const predictedMoves = useMemo(
    () =>
      (analytics?.teams ?? []).reduce(
        (total, team) =>
          total + team.players.filter((player) => player.predicted_direction !== "flat").length,
        0
      ),
    [analytics?.teams]
  );

  const activeTournament = useMemo(() => {
    if (!tournamentId) return null;
    return tournamentsData?.results?.find((tournament) => tournament.id === tournamentId) ?? null;
  }, [tournamentId, tournamentsData?.results]);

  const activeAlgorithm = useMemo(() => {
    if (!algorithmId) return null;
    return availableAlgorithms.find((algorithm) => algorithm.id === algorithmId) ?? null;
  }, [algorithmId, availableAlgorithms]);

  useEffect(() => {
    const nextParams = new URLSearchParams(searchParams);
    let changed = false;

    if (nextParams.get("tab")) {
      nextParams.delete("tab");
      changed = true;
    }

    if (tournamentId == null && isSuccessTournaments && tournamentsData?.results?.[0]?.id) {
      nextParams.set("tournamentId", String(tournamentsData.results[0].id));
      changed = true;
    }

    const preferredAlgorithmId = getPreferredAnalyticsAlgorithmId(availableAlgorithms);
    if (
      isSuccessAlgorithm &&
      preferredAlgorithmId != null &&
      (algorithmId == null || !isKnownAlgorithmId)
    ) {
      nextParams.set("algorithm", String(preferredAlgorithmId));
      changed = true;
    }

    if (changed) {
      router.replace(`${pathname}?${nextParams.toString()}`);
    }
  }, [
    pathname,
    router,
    searchParams,
    isSuccessTournaments,
    tournamentsData?.results,
    isSuccessAlgorithm,
    availableAlgorithms,
    tournamentId,
    algorithmId,
    isKnownAlgorithmId
  ]);

  const pushTournamentId = (newTournamentId: string) => {
    const newSearchParams = new URLSearchParams(searchParams || undefined);
    newSearchParams.set("tournamentId", newTournamentId);
    router.push(`${pathname}?${newSearchParams.toString()}`);
  };

  const pushAlgorithm = (newAlgorithm: string) => {
    const newSearchParams = new URLSearchParams(searchParams || undefined);
    newSearchParams.set("algorithm", newAlgorithm);
    router.push(`${pathname}?${newSearchParams.toString()}`);
  };

  const isFiltersReady = !loadingTournaments && !loadingAlgorithms;
  const isEmptyTeams = canQueryAnalytics && !!analytics && analytics.teams.length === 0;
  return (
    <div className={styles.surface}>
      <AnalyticsBriefing
        tournaments={tournamentsData?.results ?? []}
        algorithms={availableAlgorithms}
        tournamentId={tournamentId}
        algorithmId={algorithmId}
        activeTournament={activeTournament}
        activeAlgorithm={activeAlgorithm}
        summary={analytics?.summary}
        predictedMoves={predictedMoves}
        loadingTournaments={loadingTournaments}
        loadingAlgorithms={loadingAlgorithms}
        isErrorTournaments={isErrorTournaments}
        isErrorAlgorithms={isErrorAlgorithms}
        onTournamentChange={pushTournamentId}
        onAlgorithmChange={pushAlgorithm}
      />

      {canRecalculateAnalytics && tournamentId != null ? (
        <OrganizerTools tournamentId={tournamentId} workspaceId={currentWorkspaceId} />
      ) : null}

      {!isFiltersReady ? (
        <AnalyticsContentSkeleton />
      ) : tournamentId == null || algorithmId == null ? (
        <Card>
          <CardHeader>
            <CardTitle>{t("analytics.page.chooseParams")}</CardTitle>
            <CardDescription>{t("analytics.page.chooseParamsDesc")}</CardDescription>
          </CardHeader>
        </Card>
      ) : isErrorAnalytics ? (
        <Card>
          <CardHeader>
            <CardTitle>{t("analytics.page.unavailable")}</CardTitle>
            <CardDescription>{t("analytics.page.unavailableDesc")}</CardDescription>
          </CardHeader>
        </Card>
      ) : loadingAnalytics || !analytics ? (
        <AnalyticsContentSkeleton />
      ) : isEmptyTeams ? (
        <Card>
          <CardHeader>
            <CardTitle>{t("analytics.page.noTeams")}</CardTitle>
            <CardDescription>{t("analytics.page.noTeamsDesc")}</CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <>
          <AttentionTriage teams={analytics.teams} />
          <AnalyticsStandings
            teams={analytics.teams}
            performanceByPlayer={performanceByPlayer}
            distributionByTeam={distributionByTeam}
          />
          <DeepDiveSection tournamentId={tournamentId} teams={analytics.teams} />
        </>
      )}
    </div>
  );
};

const AnalyticsContentSkeleton = () => (
  <>
    {/* Needs-attention triage */}
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: 4 }).map((_, index) => (
        <Skeleton key={index} className="h-24 rounded-lg" />
      ))}
    </div>
    {/* Standings board */}
    <Skeleton className="h-[520px] rounded-lg" />
    {/* Deep dive (collapsed) */}
    <Skeleton className="h-12 rounded-lg" />
  </>
);

const AnalyticsPageFallback = () => (
  <div className={styles.surface}>
    <Card className="overflow-hidden">
      <div className="grid gap-4 p-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.9fr)]">
        <div className="space-y-4">
          <Skeleton className="h-4 w-52" />
          <Skeleton className="h-12 w-full max-w-2xl" />
          <Skeleton className="h-5 w-full max-w-xl" />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
          <Skeleton className="h-11 sm:col-span-2" />
        </div>
      </div>
    </Card>
    <AnalyticsContentSkeleton />
  </div>
);

const AnalyticsPageWrapper = () => (
  <Suspense fallback={<AnalyticsPageFallback />}>
    <AnalyticsPage />
  </Suspense>
);

export default AnalyticsPageWrapper;
