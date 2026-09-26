"use client";

import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import { PageHero, HeroCoord, HeroStat } from "@/components/site/PageHero";
import { StatusDot } from "@/components/ui/status-dot";

interface TournamentsHeroProps {
  workspaceName?: string | null;
  liveEvents: number;
  liveMatches: number;
  totalPlayers: number;
  totalTeams: number;
}

/**
 * There is deliberately NO "total tournaments" stat here.
 *
 * The list section below states its own count, and the platform-wide total from
 * `getOverallStatistics` counts a narrower set — so showing both put two
 * disagreeing tournament counts in one viewport with no way to tell which
 * answers "how many tournaments are there". The list owns that number on this
 * page; `/` and `/statistics` own the platform total.
 */
const TournamentsHero = ({
  workspaceName,
  liveEvents,
  liveMatches,
  totalPlayers,
  totalTeams,
}: TournamentsHeroProps) => {
  const t = useTranslations();
  const format = useFormatter();

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
                  <StatusDot className="text-[color:var(--aqt-status-live)] [animation:aqtPulse_2s_ease-in-out_infinite] motion-reduce:animate-none" />
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
          {/* Numbers go through the locale formatter: the raw value used to render
              `1164` beside an ICU-formatted `1,453` in the very next tile. */}
          <HeroStat label={t("common.playersLabel")} value={format.number(totalPlayers)} />
          <HeroStat
            label={t("tournamentsList.hero.teamsBalancedLabel")}
            value={format.number(totalTeams)}
          />
        </div>
      }
    />
  );
};

export default TournamentsHero;
