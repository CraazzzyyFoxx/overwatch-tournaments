"use client";

import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import { PageHero, HeroCoord, HeroStat } from "@/components/site/PageHero";
import { StatusDot } from "@/components/ui/status-dot";

interface TournamentsHeroProps {
  workspaceName?: string | null;
  liveEvents: number;
  totalPlayers: number;
  totalTeams: number;
}

/**
 * The same full-size hero as the other top-level pages. A compact header band
 * was tried and read as a thin strip with an empty middle; with descriptions
 * gone from the cards, the first card row fits under this hero on a 900px
 * viewport anyway.
 *
 * There is deliberately NO "total tournaments" stat here.
 *
 * The list section below states its own count, and the platform-wide total from
 * `getOverallStatistics` counts a narrower set — so showing both put two
 * disagreeing tournament counts in one viewport with no way to tell which
 * answers "how many tournaments are there". The list owns that number on this
 * page; `/` and `/statistics` own the platform total.
 *
 * The live counter renders only while something IS live: a nothing-happening
 * site should not spend its most prominent number saying so.
 */
const TournamentsHero = ({
  workspaceName,
  liveEvents,
  totalPlayers,
  totalTeams
}: TournamentsHeroProps) => {
  const t = useTranslations();
  const format = useFormatter();

  return (
    <PageHero
      eyebrow={workspaceName ? <HeroCoord>{workspaceName}</HeroCoord> : null}
      title={t("tournamentsList.hero.title")}
      lede={t("tournamentsList.hero.lede")}
      aside={
        <div className="flex flex-wrap gap-x-8 gap-y-5 lg:justify-end">
          {liveEvents > 0 ? (
            <HeroStat
              label={
                <span className="inline-flex items-center gap-1.5">
                  <StatusDot className="text-[color:var(--aqt-status-live)] [animation:aqtPulse_2s_ease-in-out_infinite] motion-reduce:animate-none" />
                  {t("tournamentsList.hero.liveNow")}
                </span>
              }
              value={<span className="text-[color:var(--aqt-teal)]">{liveEvents}</span>}
            />
          ) : null}
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
