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

type SortBy = "placement" | "sr" | "name";

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

  if (teamsQuery.isPending && !teamsQuery.data) {
    return <TournamentTeamsPageSkeleton />;
  }

  if (teamsQuery.isError && !teamsQuery.data) {
    return <TournamentPageState state="initial-error" onRetry={() => void teamsQuery.refetch()} />;
  }

  if (teams.length === 0) {
    return <TournamentPageState state="empty" />;
  }

  const content = (
    <div className="space-y-4">
      {teamsQuery.isFetching && !teamsQuery.isError ? (
        <p
          className="text-right text-xs font-semibold uppercase tracking-[0.14em] text-[var(--aqt-teal)]"
          role="status"
          aria-live="polite"
        >
          {t("tournamentDetail.pageState.updating")}
        </p>
      ) : null}
      <div className="section-head">
        <h2>
          {t("common.teams")} <span className="count-tag">{teams.length}</span>
        </h2>
      </div>

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
        <div className="grid gap-4 md:grid-cols-2">
          {visibleTeams.map((team) => (
            <TournamentTeamCard key={team.id} team={team} />
          ))}
        </div>
      )}
    </div>
  );

  if (teamsQuery.isError) {
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
