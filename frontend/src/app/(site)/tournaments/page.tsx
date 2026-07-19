"use client";

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import tournamentService from "@/services/tournament.service";
import encounterService from "@/services/encounter.service";
import statisticsService from "@/services/statistics.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { countByTournamentStatus, isTournamentStatusActive } from "@/lib/tournament-status";
import { Skeleton } from "@/components/ui/skeleton";

import TournamentsHero from "./components/TournamentsHero";
import FeaturedLive from "./components/FeaturedLive";
import TournamentsFilters, {
  type SortBy,
  type StatusFilter,
  type TypeFilter
} from "./components/TournamentsFilters";
import TournamentsTable from "./components/TournamentsTable";
import { groupLiveByTournament } from "./components/tournaments-helpers";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 11;

const TournamentsPageSkeleton = () => (
  <div className="space-y-6">
    <Skeleton className="h-[200px] w-full rounded-2xl" />
    <Skeleton className="h-12 w-full rounded-xl" />
    <Skeleton className="h-[520px] w-full rounded-xl" />
  </div>
);

const TournamentsPage = () => {
  const t = useTranslations();
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const workspaces = useWorkspaceStore((s) => s.workspaces);
  const workspaceName = workspaces.find((w) => w.id === workspaceId)?.name;

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<SortBy>("latest");
  const [page, setPage] = useState(1);

  const { data: tournaments, isLoading } = useQuery({
    queryKey: ["tournaments", workspaceId],
    queryFn: () => tournamentService.getAll(null, workspaceId)
  });

  const { data: overview } = useQuery({
    queryKey: tournamentQueryKeys.encountersOverview(workspaceId),
    queryFn: () => encounterService.getOverview("", {}, workspaceId),
    refetchInterval: 30_000,
    staleTime: 15_000
  });

  const { data: overall } = useQuery({
    queryKey: tournamentQueryKeys.overallStatistics(workspaceId),
    queryFn: () =>
      statisticsService.getOverallStatistics(workspaceId != null ? { workspaceId } : undefined)
  });

  const allResults = useMemo(() => tournaments?.results ?? [], [tournaments]);

  const statusCounts = useMemo(
    () => countByTournamentStatus(allResults.map((t) => t.status)),
    [allResults]
  );
  const leagueCount = useMemo(() => allResults.filter((t) => t.is_league).length, [allResults]);

  const filteredTournaments = useMemo(() => {
    let filtered = allResults;

    if (statusFilter !== "all") {
      filtered = filtered.filter((t) => t.status === statusFilter);
    }
    if (typeFilter === "standard") {
      filtered = filtered.filter((t) => !t.is_league);
    } else if (typeFilter === "league") {
      filtered = filtered.filter((t) => t.is_league);
    }

    const query = search.trim().toLowerCase();
    if (query) {
      filtered = filtered.filter(
        (t) =>
          t.name.toLowerCase().includes(query) ||
          `#${t.number}`.includes(query) ||
          String(t.number).includes(query)
      );
    }

    return [...filtered].sort((a, b) => {
      switch (sortBy) {
        case "latest":
          return new Date(b.start_date).getTime() - new Date(a.start_date).getTime();
        case "oldest":
          return new Date(a.start_date).getTime() - new Date(b.start_date).getTime();
        case "participants":
          return (b.participants_count || 0) - (a.participants_count || 0);
        default:
          return 0;
      }
    });
  }, [allResults, statusFilter, typeFilter, search, sortBy]);

  // Reset to the first page whenever a filter changes (avoids setState-in-effect).
  const handleStatusChange = (value: StatusFilter) => {
    setStatusFilter(value);
    setPage(1);
  };
  const handleTypeChange = (value: TypeFilter) => {
    setTypeFilter(value);
    setPage(1);
  };
  const handleSearchChange = (value: string) => {
    setSearch(value);
    setPage(1);
  };
  const handleSortChange = (value: SortBy) => {
    setSortBy(value);
    setPage(1);
  };

  const liveGroups = useMemo(
    () => groupLiveByTournament(overview?.featured.live ?? []),
    [overview]
  );

  const activeCount = useMemo(
    () => allResults.filter((t) => isTournamentStatusActive(t.status)).length,
    [allResults]
  );

  if (isLoading) {
    return (
      <div className="aqt-tn">
        <TournamentsPageSkeleton />
      </div>
    );
  }

  const totalTournaments = tournaments?.total ?? allResults.length;
  const totalPlayers =
    overall?.players ?? allResults.reduce((sum, t) => sum + (t.participants_count || 0), 0);

  return (
    <div className="aqt-tn space-y-6">
      <TournamentsHero
        workspaceName={workspaceName}
        liveEvents={(statusCounts.live ?? 0) + (statusCounts.playoffs ?? 0)}
        liveMatches={overview?.kpis.live_now_count ?? 0}
        totalTournaments={totalTournaments}
        activeTournaments={activeCount}
        totalPlayers={totalPlayers}
        totalTeams={overall?.teams ?? 0}
      />

      <section className="toolbar">
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <h2
            style={{
              margin: 0,
              fontFamily: "var(--display)",
              fontWeight: 700,
              fontSize: 22,
              textTransform: "uppercase",
              letterSpacing: ".04em"
            }}
          >
            {t("tournamentsList.heading.all")}
          </h2>
          <span
            className="tn-id"
            style={{
              marginLeft: 6,
              background: "hsl(0 0% 100% / 0.03)",
              border: "1px solid hsl(var(--border))",
              padding: "3px 8px",
              borderRadius: 6
            }}
          >
            {t("tournamentsList.heading.total", { count: totalTournaments })}
          </span>
        </div>
      </section>

      <FeaturedLive groups={liveGroups} />

      <TournamentsFilters
        total={allResults.length}
        statusCounts={statusCounts}
        statusFilter={statusFilter}
        onStatusChange={handleStatusChange}
        typeFilter={typeFilter}
        leagueCount={leagueCount}
        standardCount={allResults.length - leagueCount}
        onTypeChange={handleTypeChange}
        search={search}
        onSearchChange={handleSearchChange}
        sortBy={sortBy}
        onSortChange={handleSortChange}
      />

      {filteredTournaments.length === 0 ? (
        <div className="tn-card" style={{ padding: "64px 24px", textAlign: "center" }}>
          <h2
            style={{
              fontFamily: "var(--display)",
              fontWeight: 700,
              fontSize: 20,
              textTransform: "uppercase",
              letterSpacing: ".04em",
              margin: "0 0 6px"
            }}
          >
            {t("tournamentsList.empty.title")}
          </h2>
          <p style={{ color: "var(--fg-dim)", fontSize: 13, margin: 0 }}>
            {t("tournamentsList.empty.body")}
          </p>
        </div>
      ) : (
        <TournamentsTable
          tournaments={filteredTournaments}
          page={page}
          pageSize={PAGE_SIZE}
          onPageChange={setPage}
        />
      )}
    </div>
  );
};

export default TournamentsPage;
