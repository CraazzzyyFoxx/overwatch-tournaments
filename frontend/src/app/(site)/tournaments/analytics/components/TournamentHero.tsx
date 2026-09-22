"use client";

import React from "react";

import type { Tournament } from "@/types/tournament.types";
import { cn, formatDateRange } from "@/lib/utils";
import { useTranslations, useLocale } from "next-intl";
import { getTournamentStatusMeta } from "@/lib/tournament/status";
import { stageProgress } from "@/app/(site)/tournaments/components/tournaments-helpers";
import { PageHero, HeroCoord, HeroStat } from "@/components/site/PageHero";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";

interface HeroTotals {
  teams: number;
  players: number;
  groups: number;
  stages: number;
}

interface TournamentHeroProps {
  /** Null before a tournament is picked — the hero still renders a prompt. */
  tournament?: Tournament | null;
  algorithmName?: string | null;
  /** Present once analytics has loaded; the stat blocks render only then. */
  totals?: HeroTotals | null;
  /** Analytics picker controls, rendered in the right rail under the KPI blocks. */
  controlsSlot?: React.ReactNode;
}

/**
 * The tournament identity hero — id-line, title, live status + format pills and
 * the four bracket stat blocks, on the shared Editorial-Tactical hero. The
 * `controlsSlot` (analytics picker) lives in the right rail, under the KPIs.
 */
export default function TournamentHero({
  tournament,
  algorithmName,
  totals,
  controlsSlot,
}: Readonly<TournamentHeroProps>) {
  const t = useTranslations();
  const locale = useLocale();

  if (!tournament) {
    return (
      <PageHero
        title={
          <span className="text-[color:var(--aqt-fg-muted)]">
            {t("analytics.briefing.pickPrompt")}
          </span>
        }
      />
    );
  }

  const statusMeta = getTournamentStatusMeta(tournament.status);
  const stage = stageProgress(tournament, tournament.status, t);
  const dates = formatDateRange(tournament.start_date, tournament.end_date, locale);
  const statusLabel = t(`common.statusBadge.${tournament.status}`);
  const statusText = stage?.label ? `${statusLabel} · ${stage.label}` : statusLabel;

  const eyebrow = (
    <HeroCoord className="inline-flex flex-wrap items-center gap-2">
      {dates ? <span>{dates}</span> : null}
      {algorithmName ? (
        <>
          {dates ? <span className="opacity-50">·</span> : null}
          <span>{t("analytics.community.standings.rankedBy", { algorithm: algorithmName })}</span>
        </>
      ) : null}
    </HeroCoord>
  );

  const meta = (
    <>
      {statusMeta ? (
        <span className={cn(styles.cStatusPill, statusMeta.textClassName)}>
          <span className={cn(styles.cStatusDot, statusMeta.isActive && styles.cStatusDotLive)} />
          {statusText}
        </span>
      ) : null}
      <span className={styles.cMetaPill}>
        <span className={styles.cMetaPillK}>{t("analytics.hero.pillFormat")}</span>
        <span className={styles.cMetaPillV}>
          {tournament.is_league
            ? t("analytics.hero.formatLeague")
            : t("analytics.hero.formatCup")}
        </span>
      </span>
      {tournament.team_formation ? (
        <span className={styles.cMetaPill}>
          <span className={styles.cMetaPillK}>{t("analytics.hero.pillTeamsBy")}</span>
          <span className={styles.cMetaPillV}>{tournament.team_formation}</span>
        </span>
      ) : null}
    </>
  );

  const aside =
    totals || controlsSlot ? (
      <div className="flex flex-col gap-6">
        {totals ? (
          <div className="grid grid-cols-2 gap-x-7 gap-y-5 xl:grid-cols-4">
            <HeroStat
              label={t("analytics.hero.statTeams")}
              value={totals.teams}
              sub={t("analytics.hero.statTeamsSub")}
            />
            <HeroStat
              label={t("analytics.hero.statPlayers")}
              value={totals.players}
              sub={t("analytics.hero.statPlayersSub")}
            />
            <HeroStat
              label={t("analytics.hero.statGroups")}
              value={totals.groups}
              sub={t("analytics.hero.statGroupsSub")}
            />
            <HeroStat
              label={t("analytics.hero.statStages")}
              value={totals.stages}
              sub={t("analytics.hero.statStagesSub")}
            />
          </div>
        ) : null}
        {controlsSlot ? <div>{controlsSlot}</div> : null}
      </div>
    ) : undefined;

  return <PageHero eyebrow={eyebrow} title={tournament.name} meta={meta} aside={aside} />;
}
