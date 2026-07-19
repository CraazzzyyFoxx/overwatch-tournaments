"use client";

import React from "react";
import { useTranslations } from "next-intl";

import { PageHero, HeroCoord, HeroStat } from "@/components/site/PageHero";

interface TournamentsHeroProps {
  workspaceName?: string | null;
  liveEvents: number;
  liveMatches: number;
  totalTournaments: number;
  activeTournaments: number;
  totalPlayers: number;
  totalTeams: number;
}

const TournamentsHero = ({
  workspaceName,
  liveEvents,
  liveMatches,
  totalTournaments,
  activeTournaments,
  totalPlayers,
  totalTeams,
}: TournamentsHeroProps) => {
  const t = useTranslations();

  return (
    <PageHero
      eyebrow={
        <>
          <HeroCoord>{t("tournamentsList.hero.coord")}</HeroCoord>
          {workspaceName ? (
            <HeroCoord>{t("tournamentsList.hero.sector", { name: workspaceName })}</HeroCoord>
          ) : null}
        </>
      }
      title={t.rich("tournamentsList.hero.title", { em: (chunks) => <em>{chunks}</em> })}
      lede={t("tournamentsList.hero.lede")}
      aside={
        <div className="grid grid-cols-3 gap-6">
          <HeroStat
            label={
              <span className="inline-flex items-center gap-1.5">
                {liveEvents > 0 ? (
                  <span className="h-1.5 w-1.5 rounded-full bg-[color:var(--aqt-rose)] [animation:aqtPulse_2s_ease-in-out_infinite]" />
                ) : null}
                {t("tournamentsList.hero.liveNow")}
              </span>
            }
            value={
              liveEvents > 0 ? (
                <span className="text-[color:var(--aqt-teal)]">{liveEvents}</span>
              ) : (
                liveEvents
              )
            }
            sub={
              liveMatches > 0
                ? t("tournamentsList.hero.matchesInFlight", { count: liveMatches })
                : t("tournamentsList.hero.noMatchesInFlight")
            }
          />
          <HeroStat
            label={t("tournamentsList.hero.totalTournaments")}
            value={totalTournaments}
            sub={t("tournamentsList.hero.activeCount", { count: activeTournaments })}
          />
          <HeroStat
            label={t("common.playersLabel")}
            value={totalPlayers}
            sub={t("tournamentsList.hero.teamsBalanced", { count: totalTeams })}
          />
        </div>
      }
    />
  );
};

export default TournamentsHero;
