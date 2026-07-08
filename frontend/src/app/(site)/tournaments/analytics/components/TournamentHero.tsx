"use client";

import React from "react";

import type { Tournament } from "@/types/tournament.types";
import { cn } from "@/lib/utils";
import { useTranslations, useLocale } from "next-intl";
import { getTournamentStatusMeta } from "@/lib/tournament-status";
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

function formatDateRange(start: Date | string, end: Date | string, locale: "en" | "ru"): string {
  const startDate = new Date(start);
  const endDate = new Date(end);
  if (Number.isNaN(startDate.getTime())) return "";
  const loc = locale === "ru" ? "ru-RU" : "en-US";
  const formatter = new Intl.DateTimeFormat(loc, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  if (Number.isNaN(endDate.getTime())) return formatter.format(startDate);
  const withRange = formatter as Intl.DateTimeFormat & {
    formatRange?: (start: Date, end: Date) => string;
  };
  if (typeof withRange.formatRange === "function") {
    return withRange.formatRange(startDate, endDate);
  }
  return `${formatter.format(startDate)} – ${formatter.format(endDate)}`;
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
}: TournamentHeroProps) {
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
  const stage = stageProgress(tournament, tournament.status);
  const dates = formatDateRange(tournament.start_date, tournament.end_date, locale);
  const statusText = stage?.label ? `${statusMeta?.label} · ${stage.label}` : statusMeta?.label;

  const eyebrow = (
    <HeroCoord className="inline-flex flex-wrap items-center gap-2">
      <span className="text-[color:var(--aqt-fg-muted)]">#{tournament.number}</span>
      {dates ? (
        <>
          <span className="opacity-50">·</span>
          <span>{dates}</span>
        </>
      ) : null}
      {algorithmName ? (
        <>
          <span className="opacity-50">·</span>
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
