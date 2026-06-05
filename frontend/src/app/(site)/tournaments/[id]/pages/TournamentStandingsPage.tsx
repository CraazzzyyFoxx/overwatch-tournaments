"use client";

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { LayoutGrid, Circle, BarChart3 } from "lucide-react";

import tournamentService from "@/services/tournament.service";
import { Standings, Tournament } from "@/types/tournament.types";
import { Skeleton } from "@/components/ui/skeleton";
import StandingsTable from "@/components/StandingsTable";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { isTournamentStatusEnded } from "@/lib/tournament-status";
import { cn } from "@/lib/utils";
import { useTranslation } from "@/i18n/LanguageContext";


type StageView = "playoff" | "groups" | "combined";

function groupLetter(name: string): string {
  const stripped = name.replace(/group/i, "").trim();
  return (stripped.slice(0, 1) || name.slice(0, 1) || "#").toUpperCase();
}

const TournamentStandingsPage = ({ tournament }: { tournament: Tournament }) => {
  const { t } = useTranslation();
  const standingsQuery = useQuery({
    queryKey: tournamentQueryKeys.standings(tournament.id, tournament.workspace_id),
    queryFn: () => tournamentService.getStandings(tournament.id, tournament.workspace_id),
  });

  const standings = standingsQuery.data ?? [];
  const isEnded = isTournamentStatusEnded(tournament.status);
  const [view, setView] = useState<StageView>("combined");

  const { groups, playoffStandings } = useMemo(() => {
    const stageStandings = new Map<number, { name: string; standings: Standings[] }>();
    const groupStandingsList = standings.filter((standing) =>
      ["round_robin", "swiss"].includes(standing.stage?.stage_type ?? "")
    );
    const playoffStandings = standings.filter((standing) =>
      ["single_elimination", "double_elimination"].includes(standing.stage?.stage_type ?? "")
    );

    for (const standing of groupStandingsList) {
      const key = standing.stage_item_id ?? standing.stage_id;
      if (key == null) continue;
      const name =
        standing.stage_item?.name ?? standing.stage?.name ?? `Stage ${standing.stage_id}`;
      const bucket = stageStandings.get(key) ?? { name, standings: [] };
      bucket.standings.push(standing);
      stageStandings.set(key, bucket);
    }

    return {
      groups: Array.from(stageStandings.entries()).sort((a, b) => a[0] - b[0]),
      playoffStandings,
    };
  }, [standings]);

  if (standingsQuery.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-52 w-full rounded-xl" />
        <Skeleton className="h-52 w-full rounded-xl" />
      </div>
    );
  }

  const hasPlayoff = playoffStandings.length > 0;
  const hasGroups = groups.length > 0;
  const groupTeams = groups.reduce((sum, [, bucket]) => sum + bucket.standings.length, 0);

  if (!hasPlayoff && !hasGroups) {
    return (
      <div className="tn-card" style={{ padding: "48px 24px", textAlign: "center", color: "var(--fg-dim)" }}>
        {t("common.noStandings")}
      </div>
    );
  }

  const showTabs = hasPlayoff && hasGroups;
  const showPlayoff = hasPlayoff && (view === "playoff" || view === "combined");
  const showGroups = hasGroups && (view === "groups" || view === "combined");

  return (
    <div className="space-y-4">
      {showTabs && (
        <div className="section-head">
          <div className="stage-tabs">
            <button
              type="button"
              className={cn("stage-tab", view === "playoff" && "active")}
              onClick={() => setView("playoff")}
            >
              <LayoutGrid className="h-3 w-3" />
              {t("common.playoff")} <span className="count">{playoffStandings.length}</span>
            </button>
            <button
              type="button"
              className={cn("stage-tab", view === "groups" && "active")}
              onClick={() => setView("groups")}
            >
              <Circle className="h-3 w-3" />
              {t("common.groupStage")} <span className="count">{groupTeams}</span>
            </button>
            <button
              type="button"
              className={cn("stage-tab", view === "combined" && "active")}
              onClick={() => setView("combined")}
            >
              <BarChart3 className="h-3 w-3" />
              {t("common.combined")}
            </button>
          </div>
        </div>
      )}

      {showPlayoff && (
        <section className="standings-card">
          <header className="head">
            <div className="title">
              <span className="gid playoff">P</span>
              <div className="stack">
                <span className="nm">{t("common.playoffStandings")}</span>
                <span className="sub">{t("common.teamsCount", { count: playoffStandings.length })}</span>
              </div>
            </div>
            <div className="right-info">
              <div className="stat">
                <span className="k">{t("common.teams")}</span>
                <span className="v">{playoffStandings.length}</span>
              </div>
            </div>
          </header>
          <StandingsTable standings={playoffStandings} is_groups={false} crownTop={isEnded} />
        </section>
      )}

      {showGroups && (
        <div className="groups-layout">
          {groups.map(([scopeId, bucket]) => (
            <section className="standings-card" key={scopeId}>
              <header className="head">
                <div className="title">
                  <span className="gid">{groupLetter(bucket.name)}</span>
                  <div className="stack">
                    <span className="nm">{bucket.name}</span>
                    <span className="sub">
                      {t("common.teamsCount", { count: bucket.standings.length })} · {
                        bucket.standings[0]?.stage?.stage_type === "swiss"
                          ? t("common.swiss")
                          : t("common.roundRobin")
                      }
                    </span>
                  </div>
                </div>
              </header>
              <StandingsTable standings={bucket.standings} is_groups advanceCount={2} />
            </section>
          ))}
        </div>
      )}
    </div>
  );
};


export default TournamentStandingsPage;
