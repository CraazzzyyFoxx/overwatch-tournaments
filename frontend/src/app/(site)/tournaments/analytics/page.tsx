"use client";

import React, { Suspense, useCallback, useEffect, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import AnalyticsHero from "@/app/(site)/tournaments/analytics/components/AnalyticsHero";
import AnalyticsKpiStrip from "@/app/(site)/tournaments/analytics/components/AnalyticsKpiStrip";
import AnalyticsStandings from "@/app/(site)/tournaments/analytics/components/AnalyticsStandings";
import AnalyticsHorizon from "@/app/(site)/tournaments/analytics/components/AnalyticsHorizon";
import AnalyticsInsights from "@/app/(site)/tournaments/analytics/components/AnalyticsInsights";
import StandingsDistributionCard from "@/app/(site)/tournaments/analytics/components/StandingsDistributionCard";
import MatchQualityCard from "@/app/(site)/tournaments/analytics/components/MatchQualityCard";
import MLAdminToolbar from "@/app/(site)/tournaments/analytics/components/MLAdminToolbar";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";
import {
  canShowAnalyticsAdminToolbar,
  getPreferredAnalyticsAlgorithmId,
  sortAnalyticsAlgorithms
} from "@/app/(site)/tournaments/analytics/analytics.helpers";
import { usePermissions } from "@/hooks/usePermissions";
import tournamentService from "@/services/tournament.service";
import analyticsService from "@/services/analytics.service";
import { useWorkspaceStore } from "@/stores/workspace.store";

const AnalyticsPage = () => {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { hasPermission } = usePermissions();
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
      <AnalyticsHero
        tournaments={tournamentsData?.results ?? []}
        algorithms={availableAlgorithms}
        tournamentId={tournamentId}
        algorithmId={algorithmId}
        activeTournament={activeTournament}
        activeAlgorithm={activeAlgorithm}
        summary={analytics?.summary}
        loadingTournaments={loadingTournaments}
        loadingAlgorithms={loadingAlgorithms}
        isErrorTournaments={isErrorTournaments}
        isErrorAlgorithms={isErrorAlgorithms}
        adminControls={
          canRecalculateAnalytics && tournamentId != null ? (
            <MLAdminToolbar tournamentId={tournamentId} workspaceId={currentWorkspaceId} />
          ) : null
        }
        onTournamentChange={pushTournamentId}
        onAlgorithmChange={pushAlgorithm}
      />

      {!isFiltersReady ? (
        <AnalyticsContentSkeleton />
      ) : tournamentId == null || algorithmId == null ? (
        <Card>
          <CardHeader>
            <CardTitle>Choose parameters</CardTitle>
            <CardDescription>Select a tournament and an algorithm to view analytics.</CardDescription>
          </CardHeader>
        </Card>
      ) : isErrorAnalytics ? (
        <Card>
          <CardHeader>
            <CardTitle>Analytics unavailable</CardTitle>
            <CardDescription>Failed to load analytics for the selected parameters.</CardDescription>
          </CardHeader>
        </Card>
      ) : loadingAnalytics || !analytics ? (
        <AnalyticsContentSkeleton />
      ) : isEmptyTeams ? (
        <Card>
          <CardHeader>
            <CardTitle>No teams</CardTitle>
            <CardDescription>No teams found for the selected tournament.</CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <>
          <AnalyticsKpiStrip summary={analytics.summary} teams={analytics.teams} />
          <AnalyticsStandings
            teams={analytics.teams}
            performanceByPlayer={performanceByPlayer}
            distributionByTeam={distributionByTeam}
          />
          <div className={styles.split}>
            <AnalyticsHorizon teams={analytics.teams} />
            <AnalyticsInsights teams={analytics.teams} />
          </div>
          {tournamentId != null ? (
            <div className={styles.split}>
              <StandingsDistributionCard tournamentId={tournamentId} teams={analytics.teams} />
              <MatchQualityCard tournamentId={tournamentId} />
            </div>
          ) : null}
        </>
      )}
    </div>
  );
};

const AnalyticsContentSkeleton = () => (
  <>
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
      {Array.from({ length: 6 }).map((_, index) => (
        <Skeleton key={index} className="h-28 rounded-lg" />
      ))}
    </div>
    <Skeleton className="h-[520px] rounded-lg" />
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.85fr)]">
      <Skeleton className="h-[360px] rounded-lg" />
      <Skeleton className="h-[360px] rounded-lg" />
    </div>
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
