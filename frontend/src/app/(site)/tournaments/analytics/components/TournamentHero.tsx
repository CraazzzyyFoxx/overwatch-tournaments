"use client";

import React from "react";

import type { Tournament } from "@/types/tournament.types";
import { cn } from "@/lib/utils";
import { useTranslation } from "@/i18n/LanguageContext";
import { getTournamentStatusMeta } from "@/lib/tournament-status";
import { stageProgress } from "@/app/(site)/tournaments/components/tournaments-helpers";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";

interface HeroTotals {
  teams: number;
  players: number;
  groups: number;
  stages: number;
}

interface TournamentHeroProps {
  /** Null before a tournament is picked — the hero still renders the picker. */
  tournament?: Tournament | null;
  algorithmName?: string | null;
  /** Present once analytics has loaded; the stat blocks render only then. */
  totals?: HeroTotals | null;
  /** Tournament + algorithm selectors, folded into the hero header. */
  pickerSlot: React.ReactNode;
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
 * the four bracket stat blocks. Mirrors the design mock's `tn-hero`, sourced
 * from the active tournament + analytics totals. Accepts an `organizerSlot` for
 * permission-gated controls.
 */
export default function TournamentHero({
  tournament,
  algorithmName,
  totals,
  pickerSlot,
}: TournamentHeroProps) {
  const { t, locale } = useTranslation();
  const statusMeta = tournament ? getTournamentStatusMeta(tournament.status) : null;
  const stage = tournament ? stageProgress(tournament, tournament.status) : null;
  const dates = tournament
    ? formatDateRange(tournament.start_date, tournament.end_date, locale)
    : "";
  const statusText = stage?.label ? `${statusMeta?.label} · ${stage.label}` : statusMeta?.label;

  return (
    <div className={styles.cHero}>
      <span className={styles.cHeroHex} aria-hidden="true" />
      <span className={styles.cHeroGlowRose} aria-hidden="true" />
      <span className={styles.cHeroGlowTeal} aria-hidden="true" />

      <div className={styles.cHeroControls}>{pickerSlot}</div>

      {tournament ? (
        <div className={styles.cHeroInner}>
          <div className={styles.cHeroLeft}>
            <div className={styles.cHeroId}>
              <span className={styles.cHeroIdNum}>#{tournament.number}</span>
              {dates ? (
                <>
                  <span className={styles.cHeroSep}>·</span>
                  <span>{dates}</span>
                </>
              ) : null}
              {algorithmName ? (
                <>
                  <span className={styles.cHeroSep}>·</span>
                  <span>
                    {t("analytics.community.standings.rankedBy", { algorithm: algorithmName })}
                  </span>
                </>
              ) : null}
            </div>

            <h1 className={styles.cHeroTitle}>{tournament.name}</h1>

            <div className={styles.cHeroMeta}>
              {statusMeta ? (
                <span className={cn(styles.cStatusPill, statusMeta.textClassName)}>
                  <span
                    className={cn(styles.cStatusDot, statusMeta.isActive && styles.cStatusDotLive)}
                  />
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
            </div>
          </div>

          {totals ? (
            <div className={styles.cHeroStats}>
              <div className={styles.cHeroStat}>
                <span className={styles.cHeroStatL}>{t("analytics.hero.statTeams")}</span>
                <span className={styles.cHeroStatV}>{totals.teams}</span>
                <span className={styles.cHeroStatS}>{t("analytics.hero.statTeamsSub")}</span>
              </div>
              <div className={styles.cHeroStat}>
                <span className={styles.cHeroStatL}>{t("analytics.hero.statPlayers")}</span>
                <span className={styles.cHeroStatV}>{totals.players}</span>
                <span className={styles.cHeroStatS}>{t("analytics.hero.statPlayersSub")}</span>
              </div>
              <div className={styles.cHeroStat}>
                <span className={styles.cHeroStatL}>{t("analytics.hero.statGroups")}</span>
                <span className={styles.cHeroStatV}>{totals.groups}</span>
                <span className={styles.cHeroStatS}>{t("analytics.hero.statGroupsSub")}</span>
              </div>
              <div className={styles.cHeroStat}>
                <span className={styles.cHeroStatL}>{t("analytics.hero.statStages")}</span>
                <span className={styles.cHeroStatV}>{totals.stages}</span>
                <span className={styles.cHeroStatS}>{t("analytics.hero.statStagesSub")}</span>
              </div>
            </div>
          ) : null}
        </div>
      ) : (
        <div className={styles.cHeroPrompt}>{t("analytics.briefing.pickPrompt")}</div>
      )}
    </div>
  );
}
