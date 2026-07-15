"use client";

import React from "react";
import Link from "next/link";

import TournamentRegisterButton from "./TournamentRegisterButton";
import { isTournamentStatusEnded } from "@/lib/tournament-status";
import { cn, formatDateRange } from "@/lib/utils";
import { useTournamentRealtime } from "@/hooks/useTournamentRealtime";
import { useTournamentQuery } from "../_hooks/useTournamentClientData";
import type { StageSummary } from "@/types/tournament.types";

import { useTranslations, useLocale } from "next-intl";
import TournamentSectionNav from "./TournamentSectionNav";
import { TournamentShellSkeleton } from "./TournamentSkeletons";
import { PageHero, HeroCoord, HeroStat } from "@/components/site/PageHero";

type TournamentClientLayoutProps = {
  tournamentId: number;
  children: React.ReactNode;
};

type Translate = ReturnType<typeof useTranslations<never>>;

function formatLabel(stages: StageSummary[], t: Translate): string {
  const hasGroup = stages.some((s) => s.stage_type === "round_robin" || s.stage_type === "swiss");
  const hasElim = stages.some(
    (s) => s.stage_type === "single_elimination" || s.stage_type === "double_elimination"
  );
  if (hasGroup && hasElim) return t("common.formatLabel.groupsPlayoff");
  if (hasElim) return t("common.formatLabel.playoffBracket");
  if (hasGroup) return t("common.formatLabel.groupStage");
  return stages[0]?.stage_type?.replace(/_/g, " ") ?? "—";
}

export default function TournamentClientLayout({
  tournamentId,
  children
}: TournamentClientLayoutProps) {
  const t = useTranslations();
  const locale = useLocale();
  const tournamentQuery = useTournamentQuery(tournamentId);
  const tournament = tournamentQuery.data;

  useTournamentRealtime({
    tournamentId,
    workspaceId: tournament?.workspace_id
  });

  if (tournamentQuery.isPending) {
    return <TournamentShellSkeleton />;
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

  const stages = tournament.stages;
  const teamsCount = tournament.teams_count ?? 0;

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
      {tournament.is_hidden && (
        <div
          role="status"
          className="rounded-xl border px-4 py-3"
          style={{
            borderColor: "hsl(var(--border))",
            background: "hsl(var(--muted) / 0.4)"
          }}
        >
          <p className="text-sm font-semibold">{t("tournamentDetail.previewBanner")}</p>
          <p className="text-xs opacity-70">{t("tournamentDetail.previewBannerDescription")}</p>
        </div>
      )}
      <PageHero
        eyebrow={
          <HeroCoord className="inline-flex flex-wrap items-center gap-2">
            <Link
              href="/tournaments"
              className="transition-colors hover:text-[color:var(--aqt-teal)]"
            >
              {t("common.tournaments")}
            </Link>
            <span className="opacity-50">/</span>
            <span>{tournament.is_league ? t("common.league") : `#${tournament.number}`}</span>
            <span className="opacity-50">·</span>
            <span>{formatDateRange(tournament.start_date, tournament.end_date, locale)}</span>
          </HeroCoord>
        }
        title={tournament.name}
        meta={
          <>
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
            <span className="meta-pill">
              <span className="k">{t("common.teamFormation")}</span>
              <span className="v">{t(`common.${(tournament.team_formation ?? "balancer") as "balancer" | "draft"}`)}</span>
            </span>
          </>
        }
        lede={tournament.description || undefined}
        actions={
          !isEnded ? (
            <TournamentRegisterButton
              workspaceId={tournament.workspace_id}
              tournamentId={tournament.id}
              tournamentName={tournament.name}
            />
          ) : undefined
        }
        aside={
          <div className="grid grid-cols-2 gap-x-7 gap-y-5 xl:grid-cols-4">
            <HeroStat label={t("common.teams")} value={teamsCount} sub={t("common.registered")} />
            <HeroStat
              label={t("common.participants")}
              value={tournament.registrations_count ?? 0}
              sub={t("common.players")}
            />
            <HeroStat label={t("common.rostered")} value={players} sub={t("common.inTeams")} />
            <HeroStat
              label={t("common.stages")}
              value={stages.length}
              sub={`${completedStages} ${t("common.done")}`}
            />
          </div>
        }
      />

      <TournamentSectionNav
        tournamentId={String(tournamentId)}
        status={tournament.status}
        stages={stages}
        teamFormation={tournament.team_formation}
      />

      <section className="min-w-0">{children}</section>
    </div>
  );
}
