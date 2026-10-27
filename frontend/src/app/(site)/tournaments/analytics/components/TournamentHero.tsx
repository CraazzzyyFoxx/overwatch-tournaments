"use client";

import React from "react";
import { useTranslations } from "next-intl";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { HeroCoord, PageHero } from "@/components/site/PageHero";
import { TournamentStatusPill } from "@/components/tournaments/StatusPill";
import type { AnalyticsHeroParts } from "@/disciplines/types";
import { formatDateRange } from "@/lib/datetime";
import { useFormatter } from "@/lib/datetime/client";
import { stageProgress } from "@/lib/tournament/stage-progress";
import { getTournamentStatusMeta } from "@/lib/tournament/status";
import type { TeamFormation, Tournament } from "@/types/tournament.types";

interface TournamentHeroProps {
  /** Null before a tournament is picked — the hero still renders the prompt and the pickers. */
  tournament?: Tournament | null;
  /** What the game's board contributes: the lede, its figures, its actions and its own controls. */
  parts: AnalyticsHeroParts;
  /** The tournament picker row (the board's controls already inside it). */
  picker: React.ReactNode;
}

/**
 * The analytics page's header on the shared `PageHero`, shaped like the
 * tournament's own: crumbs and dates, the name with its status, one meta line;
 * the board's reading of the result is the lede and its figures fill the right
 * column above the pickers.
 */
export default function TournamentHero({ tournament, parts, picker }: Readonly<TournamentHeroProps>) {
  const t = useTranslations();
  const format = useFormatter();
  const dates = tournament ? formatDateRange(format, tournament.start_date, tournament.end_date) : null;

  // Each separator travels with the crumb after it, so a wrapped line never ends on a bare "/".
  const eyebrow = (
    <HeroCoord className="inline-flex flex-wrap items-center gap-x-4 gap-y-1">
      <HoverPrefetchLink href="/tournaments" className="transition-colors hover:text-[color:var(--aqt-teal)]">
        {t("common.tournaments")}
      </HoverPrefetchLink>
      {[t("common.analytics"), dates].map((crumb) =>
        crumb ? (
          <span key={crumb} className="inline-flex items-center gap-4">
            <span className="opacity-50">/</span>
            <span>{crumb}</span>
          </span>
        ) : null
      )}
    </HeroCoord>
  );

  const aside = (
    <div className="flex flex-col gap-6">
      {parts.stats}
      {picker}
    </div>
  );

  if (!tournament) {
    return (
      <PageHero
        eyebrow={eyebrow}
        title={<span className="text-[color:var(--aqt-fg-muted)]">{t("analytics.briefing.pickPrompt")}</span>}
        aside={aside}
      />
    );
  }

  const statusLabel = t(`common.statusBadge.${tournament.status}`);
  const stage = stageProgress(tournament, tournament.status, t);
  const facts = [
    tournament.is_league ? t("analytics.hero.formatLeague") : t("analytics.hero.formatCup"),
    tournament.team_formation ? t(`common.${tournament.team_formation as TeamFormation}`) : null,
    parts.counts
      ? t("tournamentDetail.header.teamsAndPlayers", {
          teams: parts.counts.teams,
          players: parts.counts.players
        })
      : null
  ].filter((fact): fact is string => fact !== null);

  return (
    <PageHero
      eyebrow={eyebrow}
      title={
        <span className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <HoverPrefetchLink
            href={`/tournaments/${tournament.slug}`}
            className="min-w-0 transition-colors hover:text-[color:var(--aqt-teal)]"
          >
            {tournament.name}
          </HoverPrefetchLink>
          <TournamentStatusPill status={getTournamentStatusMeta(tournament.status).variant} className="shrink-0">
            {stage?.label ? `${statusLabel} · ${stage.label}` : statusLabel}
          </TournamentStatusPill>
        </span>
      }
      meta={
        <p className="text-caption text-[color:var(--aqt-fg-muted)]">
          {facts.map((fact, index) => (
            <React.Fragment key={fact}>
              {index > 0 ? <span className="px-1.5 text-[color:var(--aqt-fg-dim)]">·</span> : null}
              {fact}
            </React.Fragment>
          ))}
        </p>
      }
      lede={parts.lede}
      actions={parts.actions}
      aside={aside}
    />
  );
}
