"use client";

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, Circle, LayoutGrid } from "lucide-react";
import { useTranslations } from "next-intl";

import StandingsTable from "@/components/StandingsTable";
import { isTournamentStatusEnded } from "@/lib/tournament-status";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { cn } from "@/lib/utils";
import tournamentService from "@/services/tournament.service";
import { Stage, Standings, Tournament } from "@/types/tournament.types";

import styles from "../TournamentDetail.module.css";
import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentStandingsSkeleton } from "../_components/TournamentSkeletons";
import { useTournamentQuery } from "../_hooks/useTournamentClientData";
import {
  getPublicPageQueryPresentation,
  type PublicPageQueryState
} from "./publicPageQueryPresentation";

type StageView = "playoff" | "groups" | "combined";

export const getStandingsQueryPresentation = (state: PublicPageQueryState) =>
  getPublicPageQueryPresentation(state);

type PublicStandingsSource = {
  getStandings: (tournamentId: number, workspaceId: number | null) => Promise<Standings[]>;
  getStages: (tournamentId: number) => Promise<Stage[]>;
};

const publicStandingsSource: PublicStandingsSource = {
  getStandings: (tournamentId, workspaceId) =>
    tournamentService.getStandings(tournamentId, workspaceId),
  getStages: (tournamentId) => tournamentService.getStages(tournamentId)
};

export function getPublicStandingsQueryPlan(
  tournament: Tournament | undefined,
  source: PublicStandingsSource = publicStandingsSource
) {
  const enabled = tournament !== undefined;
  const tournamentId = tournament?.id ?? 0;

  return {
    standings: {
      queryKey: tournamentQueryKeys.standings(tournamentId, tournament?.workspace_id),
      queryFn: () => {
        if (!tournament) return Promise.resolve([]);
        return source.getStandings(tournament.id, tournament.workspace_id);
      },
      enabled
    },
    stages: {
      queryKey: tournamentQueryKeys.stages(tournamentId),
      queryFn: () => {
        if (!tournament) return Promise.resolve([]);
        return source.getStages(tournament.id);
      },
      enabled
    }
  };
}

function groupLetter(name: string): string {
  const stripped = name.replace(/group/i, "").trim();
  return (stripped.slice(0, 1) || name.slice(0, 1) || "#").toUpperCase();
}

const TournamentStandingsPage = ({ tournamentId }: { tournamentId: number }) => {
  const t = useTranslations();
  const tournamentQuery = useTournamentQuery(tournamentId);
  const tournament = tournamentQuery.data;
  const queryPlan = getPublicStandingsQueryPlan(tournament);
  const standingsQuery = useQuery(queryPlan.standings);
  const stagesQuery = useQuery(queryPlan.stages);
  const [view, setView] = useState<StageView>("combined");
  const standings = standingsQuery.data ? standingsQuery.data : [];
  const stages = stagesQuery.data ? stagesQuery.data : [];
  const { groups, playoffStandings } = useMemo(() => {
    const stageStandings = new Map<number, { name: string; standings: Standings[] }>();
    const groupStandingsList = standings.filter((standing) =>
      ["round_robin", "swiss"].includes(standing.stage?.stage_type ?? "")
    );
    const playoff = standings.filter((standing) =>
      ["single_elimination", "double_elimination"].includes(standing.stage?.stage_type ?? "")
    );

    for (const standing of groupStandingsList) {
      const key = standing.stage_item_id ?? standing.stage_id;
      if (key == null) continue;
      const name =
        standing.stage_item?.name ??
        standing.stage?.name ??
        t("common.stageWithId", { id: standing.stage_id ?? key });
      const bucket = stageStandings.get(key) ?? { name, standings: [] };
      bucket.standings.push(standing);
      stageStandings.set(key, bucket);
    }

    return {
      groups: Array.from(stageStandings.entries()).sort((a, b) => a[0] - b[0]),
      playoffStandings: playoff
    };
  }, [standings, t]);
  const hasPageData = standingsQuery.data !== undefined && stagesQuery.data !== undefined;
  const presentation = getStandingsQueryPresentation({
    data: hasPageData ? { standings: standingsQuery.data, stages: stagesQuery.data } : undefined,
    itemCount: standings.length,
    isPending: standingsQuery.isPending || stagesQuery.isPending,
    isError: standingsQuery.isError || stagesQuery.isError,
    isFetching: standingsQuery.isFetching || stagesQuery.isFetching
  });

  if (!tournament) {
    if (tournamentQuery.isError) {
      return (
        <TournamentPageState state="initial-error" onRetry={() => void tournamentQuery.refetch()} />
      );
    }
    return <TournamentStandingsSkeleton />;
  }
  if (presentation.initialState === "error") {
    return (
      <TournamentPageState
        state="initial-error"
        onRetry={() => void Promise.all([standingsQuery.refetch(), stagesQuery.refetch()])}
      />
    );
  }
  if (presentation.initialState === "skeleton" || presentation.contentState === null) {
    return <TournamentStandingsSkeleton />;
  }

  const isEnded = isTournamentStatusEnded(tournament.status);
  const hasPlayoff = playoffStandings.length > 0;
  const hasGroups = groups.length > 0;
  const groupTeams = groups.reduce((sum, [, bucket]) => sum + bucket.standings.length, 0);
  const showTabs = hasPlayoff && hasGroups;
  const showPlayoff = hasPlayoff && (view === "playoff" || view === "combined");
  const showGroups = hasGroups && (view === "groups" || view === "combined");
  const showStageEmpty = presentation.contentState === "content" && !showPlayoff && !showGroups;

  const content = (
    <section className={styles.publicDataPage} aria-labelledby="tournament-standings-title">
      <header className={styles.pageHeading}>
        <div className={styles.pageHeadingCopy}>
          <span className={styles.pageEyebrow}>
            {t("tournamentDetail.publicPages.standings.eyebrow")}
          </span>
          <div className={styles.pageTitleRow}>
            <h2 className={styles.pageTitle} id="tournament-standings-title">
              {t("common.standings")}
            </h2>
            <span className={styles.pageCount}>{standings.length}</span>
          </div>
          <p className={styles.pageContext}>
            {t("tournamentDetail.publicPages.standings.context")}
          </p>
        </div>
        {presentation.showUpdating ? (
          <span className={styles.updating} role="status" aria-live="polite">
            {t("tournamentDetail.pageState.updating")}
          </span>
        ) : null}
      </header>

      {showTabs ? (
        <div
          className={styles.stageNavigation}
          role="group"
          aria-label={t("tournamentDetail.publicPages.standings.stageViewLabel")}
        >
          <div className="stage-tabs">
            <button
              type="button"
              className={cn("stage-tab", view === "playoff" && "active")}
              aria-pressed={view === "playoff"}
              onClick={() => setView("playoff")}
            >
              <LayoutGrid className="h-3 w-3" aria-hidden="true" />
              {t("common.playoff")} <span className="count">{playoffStandings.length}</span>
            </button>
            <button
              type="button"
              className={cn("stage-tab", view === "groups" && "active")}
              aria-pressed={view === "groups"}
              onClick={() => setView("groups")}
            >
              <Circle className="h-3 w-3" aria-hidden="true" />
              {t("common.groupStage")} <span className="count">{groupTeams}</span>
            </button>
            <button
              type="button"
              className={cn("stage-tab", view === "combined" && "active")}
              aria-pressed={view === "combined"}
              onClick={() => setView("combined")}
            >
              <BarChart3 className="h-3 w-3" aria-hidden="true" />
              {t("common.combined")}
            </button>
          </div>
        </div>
      ) : null}

      {presentation.contentState === "empty" ? (
        <TournamentPageState
          state="empty"
          title={t("tournamentDetail.publicPages.standings.emptyTitle")}
          description={t("tournamentDetail.publicPages.standings.emptyDescription")}
        />
      ) : showStageEmpty ? (
        <div className={styles.stageEmpty}>
          <TournamentPageState
            state="empty"
            title={t("tournamentDetail.publicPages.standings.stageEmptyTitle")}
            description={t("tournamentDetail.publicPages.standings.stageEmptyDescription")}
          />
        </div>
      ) : (
        <div className={styles.standingsSections}>
          {showPlayoff ? (
            <section className="standings-card" aria-labelledby="playoff-standings-title">
              <header className="head">
                <div className="title">
                  <span className="gid playoff" aria-hidden="true">
                    P
                  </span>
                  <div className="stack">
                    <h3 className="nm" id="playoff-standings-title">
                      {t("common.playoffStandings")}
                    </h3>
                    <span className="sub">
                      {t("common.teamsCount", { count: playoffStandings.length })}
                    </span>
                  </div>
                </div>
                <div className="right-info" aria-hidden="true">
                  <div className="stat">
                    <span className="k">{t("common.teams")}</span>
                    <span className="v">{playoffStandings.length}</span>
                  </div>
                </div>
              </header>
              <StandingsTable
                standings={playoffStandings}
                stages={stages}
                is_groups={false}
                crownTop={isEnded}
              />
            </section>
          ) : null}

          {showGroups ? (
            <div className="groups-layout">
              {groups.map(([scopeId, bucket]) => {
                const headingId = `standings-stage-${scopeId}`;
                return (
                  <section className="standings-card" key={scopeId} aria-labelledby={headingId}>
                    <header className="head">
                      <div className="title">
                        <span className="gid" aria-hidden="true">
                          {groupLetter(bucket.name)}
                        </span>
                        <div className="stack">
                          <h3 className="nm" id={headingId}>
                            {bucket.name}
                          </h3>
                          <span className="sub">
                            {t("common.teamsCount", { count: bucket.standings.length })} ·{" "}
                            {bucket.standings[0]?.stage?.stage_type === "swiss"
                              ? t("common.swiss")
                              : t("common.roundRobin")}
                          </span>
                        </div>
                      </div>
                    </header>
                    <StandingsTable standings={bucket.standings} stages={stages} is_groups />
                  </section>
                );
              })}
            </div>
          ) : null}
        </div>
      )}
    </section>
  );

  if (presentation.showRefreshError) {
    return (
      <TournamentPageState
        state="refresh-error"
        onRetry={() => void Promise.all([standingsQuery.refetch(), stagesQuery.refetch()])}
        isUpdating={standingsQuery.isFetching || stagesQuery.isFetching}
      >
        {content}
      </TournamentPageState>
    );
  }

  return content;
};

export default TournamentStandingsPage;
