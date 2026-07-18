"use client";

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Tournament } from "@/types/tournament.types";
import { Team } from "@/types/team.types";
import teamService from "@/services/team.service";
import { TournamentTeamCard } from "@/components/TournamentTeamCard";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { cn } from "@/lib/utils";

import { useTranslations } from "next-intl";
import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentTeamsSkeleton } from "../_components/TournamentSkeletons";
import styles from "../TournamentDetail.module.css";

type SortBy = "placement" | "sr" | "name";
type TeamsQueryPresentation = {
  initialState: "skeleton" | "error" | null;
  contentState: "empty" | "teams" | null;
  showUpdating: boolean;
  showRefreshError: boolean;
};

export function getTeamsQueryPresentation({
  data,
  teamCount,
  isPending,
  isError,
  isFetching
}: {
  data: unknown;
  teamCount: number;
  isPending: boolean;
  isError: boolean;
  isFetching: boolean;
}): TeamsQueryPresentation {
  const hasCachedData = data !== undefined;

  return {
    initialState: hasCachedData ? null : isError ? "error" : isPending ? "skeleton" : null,
    contentState: hasCachedData ? (teamCount === 0 ? "empty" : "teams") : null,
    showUpdating: hasCachedData && isFetching && !isError,
    showRefreshError: hasCachedData && isError
  };
}

export const TournamentTeamsPageSkeleton = () => {
  return <TournamentTeamsSkeleton />;
};

function sortTeams(teams: Team[], sortBy: SortBy): Team[] {
  return [...teams].sort((a, b) => {
    switch (sortBy) {
      case "placement": {
        const ap = a.placement ?? Number.POSITIVE_INFINITY;
        const bp = b.placement ?? Number.POSITIVE_INFINITY;
        return ap - bp;
      }
      case "sr":
        return (b.avg_sr ?? 0) - (a.avg_sr ?? 0);
      case "name":
        return a.name.localeCompare(b.name);
      default:
        return 0;
    }
  });
}

const TournamentTeamsPage = ({ tournament }: { tournament: Tournament }) => {
  const t = useTranslations();
  const teamsQuery = useQuery({
    queryKey: tournamentQueryKeys.teams(tournament.id, tournament.workspace_id),
    queryFn: () =>
      teamService.getAll({
        tournamentId: tournament.id,
        workspaceId: tournament.workspace_id
      })
  });

  const [groupFilter, setGroupFilter] = useState<string>("all");
  const [sortBy, setSortBy] = useState<SortBy>("placement");

  const teams = useMemo(() => teamsQuery.data?.results ?? [], [teamsQuery.data]);

  const groups = useMemo(() => {
    const counts = new Map<string, number>();
    for (const team of teams) {
      const name = team.group?.name;
      if (name) counts.set(name, (counts.get(name) ?? 0) + 1);
    }
    return Array.from(counts.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [teams]);

  const visibleTeams = useMemo(() => {
    const filtered =
      groupFilter === "all"
        ? teams
        : teams.filter((team) => team.group?.name === groupFilter);
    return sortTeams(filtered, sortBy);
  }, [teams, groupFilter, sortBy]);

  const presentation = getTeamsQueryPresentation({
    data: teamsQuery.data,
    teamCount: teams.length,
    isPending: teamsQuery.isPending,
    isError: teamsQuery.isError,
    isFetching: teamsQuery.isFetching
  });

  if (presentation.initialState === "error") {
    return <TournamentPageState state="initial-error" onRetry={() => void teamsQuery.refetch()} />;
  }

  if (presentation.initialState === "skeleton" || presentation.contentState === null) {
    return <TournamentTeamsPageSkeleton />;
  }

  const content = (
    <div className={cn("space-y-4", styles.teamsContent)}>
      {presentation.showUpdating ? (
        <p className={styles.updatingRow} role="status" aria-live="polite">
          <span className={styles.updating}>{t("tournamentDetail.pageState.updating")}</span>
        </p>
      ) : null}
      {presentation.contentState === "empty" ? (
        <TournamentPageState state="empty" />
      ) : (
        <>
          <div className="filters">
            <button
              type="button"
              className={cn("filter-chip", groupFilter === "all" && "active")}
              onClick={() => setGroupFilter("all")}
            >
              {t("common.all")} <span className="count">{teams.length}</span>
            </button>
            {groups.map(([name, count]) => (
              <button
                key={name}
                type="button"
                className={cn("filter-chip", groupFilter === name && "active")}
                onClick={() => setGroupFilter(name)}
              >
                {t("common.group")} {name} <span className="count">{count}</span>
              </button>
            ))}

            <select
              className="filter-sort"
              style={{ marginLeft: "auto" }}
              value={sortBy}
              onChange={(event) => setSortBy(event.target.value as SortBy)}
              aria-label={t("tournamentDetail.sortTeams")}
            >
              <option value="placement">{t("common.byPlacement")}</option>
              <option value="sr">{t("common.byAvgSr")}</option>
              <option value="name">{t("common.byName")}</option>
            </select>
          </div>

          {visibleTeams.length === 0 ? (
            <TournamentPageState state="filtered-empty" onReset={() => setGroupFilter("all")} />
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {visibleTeams.map((team) => (
                <TournamentTeamCard key={team.id} team={team} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );

  if (presentation.showRefreshError) {
    return (
      <TournamentPageState
        state="refresh-error"
        onRetry={() => void teamsQuery.refetch()}
        isUpdating={teamsQuery.isFetching}
      >
        {content}
      </TournamentPageState>
    );
  }

  return content;
};

export default TournamentTeamsPage;
