"use client";

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Tournament } from "@/types/tournament.types";
import { Team } from "@/types/team.types";
import teamService from "@/services/team.service";
import { TournamentTeamCard, TournamentTeamCardSkeleton } from "@/components/TournamentTeamCard";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { cn } from "@/lib/utils";

import { useTranslation } from "@/i18n/LanguageContext";

type SortBy = "placement" | "sr" | "name";

export const TournamentTeamsPageSkeleton = () => {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, index) => (
          <TournamentTeamCardSkeleton key={index} />
        ))}
      </div>
    </div>
  );
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
  const { t } = useTranslation();
  const teamsQuery = useQuery({
    queryKey: tournamentQueryKeys.teams(tournament.id),
    queryFn: () => teamService.getAll(tournament.id),
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

  if (teamsQuery.isLoading) {
    return <TournamentTeamsPageSkeleton />;
  }

  return (
    <div className="space-y-4">
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
        <div className="tn-card" style={{ padding: "48px 24px", textAlign: "center", color: "var(--fg-dim)" }}>
          {t("common.noTeams")}
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {visibleTeams.map((team) => (
            <TournamentTeamCard key={team.id} team={team} />
          ))}
        </div>
      )}
    </div>
  );
};

export default TournamentTeamsPage;
