"use client";

import React from "react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import TournamentRegisterButton from "./TournamentRegisterButton";
import { TOURNAMENT_STATUS_META, isTournamentStatusEnded } from "@/lib/tournament-status";
import { cn, formatDateRange } from "@/lib/utils";
import { useTournamentRealtime } from "@/hooks/useTournamentRealtime";
import { useTournamentQuery, useTournamentStagesQuery } from "../_hooks/useTournamentClientData";
import { useQuery } from "@tanstack/react-query";
import teamService from "@/services/team.service";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import type { Stage } from "@/types/tournament.types";

import { useTranslation } from "@/i18n/LanguageContext";
import TournamentSectionNav from "./TournamentSectionNav";

type TournamentClientLayoutProps = {
  tournamentId: number;
  children: React.ReactNode;
};

function formatLabel(stages: Stage[], t: (key: string) => string): string {
  const hasGroup = stages.some((s) => s.stage_type === "round_robin" || s.stage_type === "swiss");
  const hasElim = stages.some(
    (s) => s.stage_type === "single_elimination" || s.stage_type === "double_elimination"
  );
  if (hasGroup && hasElim) return t("common.formatLabel.groupsPlayoff");
  if (hasElim) return t("common.formatLabel.playoffBracket");
  if (hasGroup) return t("common.formatLabel.groupStage");
  return stages[0]?.stage_type?.replace(/_/g, " ") ?? "—";
}

function TournamentLayoutSkeleton() {
  return (
    <div className="aqt-tn space-y-4">
      <Skeleton className="h-4 w-64" />
      <Skeleton className="h-[180px] w-full rounded-2xl" />
      <Skeleton className="h-10 w-full max-w-xl rounded-lg" />
      <Skeleton className="h-72 w-full rounded-xl" />
    </div>
  );
}

export default function TournamentClientLayout({
  tournamentId,
  children
}: TournamentClientLayoutProps) {
  const { t, locale } = useTranslation();
  const tournamentQuery = useTournamentQuery(tournamentId);
  const stagesQuery = useTournamentStagesQuery(tournamentId);
  const tournament = tournamentQuery.data;
  const stages = stagesQuery.data ?? [];

  const teamsQuery = useQuery({
    queryKey: tournamentQueryKeys.teamsCount(tournamentId),
    queryFn: () => teamService.getCount(tournamentId),
    enabled: Boolean(tournamentId)
  });
  const teamsCount = teamsQuery.data ?? 0;

  useTournamentRealtime({
    tournamentId,
    workspaceId: tournament?.workspace_id
  });

  if (tournamentQuery.isLoading || stagesQuery.isLoading) {
    return <TournamentLayoutSkeleton />;
  }

  if (!tournament) {
    return (
      <div className="aqt-tn">
        <div
          className="tn-card"
          style={{ padding: "48px 24px", textAlign: "center", color: "var(--fg-dim)" }}
        >
          {t("common.tournamentNotFound")}
        </div>
      </div>
    );
  }

  const designClass =
    tournament.status === "live" || tournament.status === "playoffs"
      ? "live"
      : tournament.status === "registration" || tournament.status === "check_in"
        ? "upcoming"
        : tournament.status === "completed" || tournament.status === "archived"
          ? "finished"
          : "draft";
  const isEnded = isTournamentStatusEnded(tournament.status);
  const players = tournament.participants_count ?? 0;
  const completedStages = stages.filter((stage) => stage.is_completed).length;

  return (
    <div className="aqt-tn space-y-4">
      <p className="crumb">
        <Link href="/tournaments">{t("common.tournaments")}</Link>
        <span className="sep">/</span>
        <span>{tournament.name}</span>
      </p>

      <section className={cn("tn-hero", designClass !== "live" && `status-${designClass}`)}>
        <div className="hex" />
        <div className="glow-rose" />
        <div className="glow-teal" />

        {!isEnded && (
          <div className="tn-actions">
            <TournamentRegisterButton
              workspaceId={tournament.workspace_id}
              tournamentId={tournament.id}
              tournamentName={tournament.name}
            />
          </div>
        )}

        <div className="tn-hero-inner">
          <div className="tn-h-left">
            <div className="tn-id-line">
              <span className="id">
                {tournament.is_league ? t("common.league") : `#${tournament.number}`}
              </span>
              <span>·</span>
              <span>{formatDateRange(tournament.start_date, tournament.end_date, locale)}</span>
            </div>

            <h1 className="tn-title">{tournament.name}</h1>

            <div className="tn-meta-row">
              <span className={cn("status-pill", designClass)}>
                {(tournament.status === "live" || tournament.status === "playoffs") && (
                  <span className="dot" />
                )}
                {t(`common.statusBadge.${tournament.status}`)}
              </span>
              <span className="meta-pill">
                <span className="k">{t("common.format")}</span>
                <span className="v">{formatLabel(stages, t)}</span>
              </span>
            </div>

            {tournament.description && (
              <p
                style={{
                  marginTop: 6,
                  maxWidth: "44rem",
                  fontSize: 12.5,
                  lineHeight: 1.6,
                  color: "var(--fg-dim)"
                }}
              >
                {tournament.description}
              </p>
            )}
          </div>

          <div className="tn-h-stats">
            <div className="tn-h-stat">
              <span className="l">{t("common.teams")}</span>
              <span className="v">{teamsCount}</span>
              <span className="s">{t("common.registered")}</span>
            </div>
            <div className="tn-h-stat">
              <span className="l">{t("common.participants")}</span>
              <span className="v">{tournament.registrations_count ?? 0}</span>
              <span className="s">{t("common.players")}</span>
            </div>
            <div className="tn-h-stat">
              <span className="l">{t("common.rostered")}</span>
              <span className="v">{players}</span>
              <span className="s">{t("common.inTeams")}</span>
            </div>
            <div className="tn-h-stat">
              <span className="l">{t("common.stages")}</span>
              <span className="v">{stages.length}</span>
              <span className="s">
                {completedStages} {t("common.done")}
              </span>
            </div>
          </div>
        </div>
      </section>

      <TournamentSectionNav
        tournamentId={String(tournamentId)}
        status={tournament.status}
        stages={stages}
      />

      <section className="min-w-0">{children}</section>
    </div>
  );
}
