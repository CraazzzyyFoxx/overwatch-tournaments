"use client";

import React, { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import AnalyticsPicker from "@/app/(site)/tournaments/analytics/components/AnalyticsPicker";
import TournamentHero from "@/app/(site)/tournaments/analytics/components/TournamentHero";
import VerdictBanner from "@/app/(site)/tournaments/analytics/components/VerdictBanner";
import KpiRail from "@/app/(site)/tournaments/analytics/components/KpiRail";
import MasterDetail from "@/app/(site)/tournaments/analytics/components/MasterDetail";
import { type StandingsMode } from "@/app/(site)/tournaments/analytics/components/StandingsList";
import HowItWorksCard from "@/app/(site)/tournaments/analytics/components/HowItWorksCard";
import BottomSheet, {
  type SheetState
} from "@/app/(site)/tournaments/analytics/components/BottomSheet";
import { type GlossaryTerm } from "@/app/(site)/tournaments/analytics/analytics-glossary";
import OrganizerTools from "@/app/(site)/tournaments/analytics/components/OrganizerTools";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";
import {
  canShowAnalyticsAdminToolbar,
  getPreferredAnalyticsAlgorithmId,
  sortAnalyticsAlgorithms,
  type KpiId
} from "@/app/(site)/tournaments/analytics/analytics.helpers";
import { useAnalyticsViewModel } from "@/app/(site)/tournaments/analytics/useAnalyticsViewModel";
import { cn } from "@/lib/utils";
import { usePermissions } from "@/hooks/usePermissions";
import { useTranslation } from "@/i18n/LanguageContext";
import tournamentService from "@/services/tournament.service";
import analyticsService from "@/services/analytics.service";
import { useWorkspaceStore } from "@/stores/workspace.store";

const AnalyticsPage = () => {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { hasPermission, canAccessPermission } = usePermissions();
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
  // v2 ML reads (performance, Monte-Carlo distribution, match quality, SHAP) are
  // permission-gated server-side. Gate the fetches too so the public/community
  // baseline (v1 + derived impact) never fires a 403 query.
  const canReadV2 = canAccessPermission("analytics.read", currentWorkspaceId);

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
    enabled: tournamentId != null && canReadV2
  });

  const performanceByPlayer = useMemo(
    () =>
      new Map(
        (performanceRows ?? []).map((row) => [row.player_id, row])
      ),
    [performanceRows]
  );

  // Monte Carlo standings distribution — woven into the team detail (and the
  // organizer table view); gated to analytics.read viewers.
  const { data: standingsRows } = useQuery({
    queryKey: ["analytics-standings-distribution", tournamentId, undefined],
    queryFn: () => analyticsService.getStandingsDistribution(tournamentId!),
    enabled: tournamentId != null && canReadV2,
    staleTime: 60_000
  });

  const distributionByTeam = useMemo(
    () => new Map((standingsRows ?? []).map((row) => [row.team_id, row])),
    [standingsRows]
  );

  // Fan-facing view model: per-player impact, the six KPIs, the verdict and the
  // group count. Derived from the public v1 payload (+ v2 impact when allowed).
  const viewModel = useAnalyticsViewModel(analytics, performanceByPlayer, canReadV2);

  // Glossary / how-it-works explainer sheet, opened by info dots + the help card.
  const [sheet, setSheet] = useState<SheetState | null>(null);
  const explain = useCallback((term: GlossaryTerm) => setSheet({ kind: "term", term }), []);
  const showHow = useCallback(() => setSheet({ kind: "how" }), []);
  const closeSheet = useCallback(() => setSheet(null), []);

  // Standings sort/filter is lifted so the KPI cards can drive it (triage folds
  // into the standings instead of a separate section).
  const [standingsMode, setStandingsMode] = useState<StandingsMode>("standings");
  const standingsRef = React.useRef<HTMLDivElement | null>(null);
  const onKpiSelect = useCallback((id: KpiId) => {
    setStandingsMode(id === "watch" ? "watch" : "movers");
    standingsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

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
  const picker = (
    <AnalyticsPicker
      tournaments={tournamentsData?.results ?? []}
      algorithms={availableAlgorithms}
      tournamentId={tournamentId}
      algorithmId={algorithmId}
      loadingTournaments={loadingTournaments}
      loadingAlgorithms={loadingAlgorithms}
      isErrorTournaments={isErrorTournaments}
      isErrorAlgorithms={isErrorAlgorithms}
      onTournamentChange={pushTournamentId}
      onAlgorithmChange={pushAlgorithm}
    />
  );

  return (
    <div className={cn(styles.surface, styles.cRoot)}>
      {/* Persistent header: tournament identity + the pickers, folded together. */}
      <TournamentHero
        tournament={activeTournament}
        algorithmName={activeAlgorithm?.name}
        totals={
          analytics && activeTournament
            ? {
                teams: analytics.summary.total_teams,
                players: analytics.summary.total_players,
                groups: viewModel?.groupCount ?? 0,
                stages: activeTournament.stages?.length ?? 0
              }
            : null
        }
        pickerSlot={picker}
      />

      {canRecalculateAnalytics && tournamentId != null ? (
        <OrganizerTools tournamentId={tournamentId} workspaceId={currentWorkspaceId} />
      ) : null}

      {!isFiltersReady ? (
        <AnalyticsContentSkeleton />
      ) : tournamentId == null || algorithmId == null ? null : isErrorAnalytics ? (
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
      ) : viewModel ? (
        <>
          <VerdictBanner verdict={viewModel.verdict} onExplain={explain} />
          <KpiRail kpis={viewModel.kpis} onExplain={explain} onSelect={onKpiSelect} />
          <div ref={standingsRef}>
            <MasterDetail
              key={`${tournamentId}-${algorithmId}`}
              tournamentId={tournamentId}
              teams={viewModel.teams}
              algorithmName={activeAlgorithm?.name}
              canReadV2={canReadV2}
              mode={standingsMode}
              onModeChange={setStandingsMode}
              performanceByPlayer={performanceByPlayer}
              distributionByTeam={distributionByTeam}
              onExplain={explain}
            />
          </div>
          <HowItWorksCard onOpen={showHow} />
        </>
      ) : null}

      <BottomSheet state={sheet} onClose={closeSheet} />
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
