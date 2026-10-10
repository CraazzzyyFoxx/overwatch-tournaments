"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import { PageHero } from "@/components/site/PageHero";
import { StatusDot } from "@/components/ui/status-dot";
import { cn } from "@/lib/utils";

interface TournamentsHeroProps {
  workspaceName?: string | null;
  liveEvents: number;
  totalPlayers: number;
  totalTeams: number;
}

/**
 * One stat: value and label on a single baseline below `md` (three stats cost
 * one line on a phone), label-over-value from `md` like every other hero.
 *
 * Not `HeroStat`: its ~34px value is sized for a landing hero and would outweigh
 * the 30px title of this header band.
 */
const Stat = ({
  label,
  value,
  accent = false
}: Readonly<{ label: ReactNode; value: ReactNode; accent?: boolean }>) => (
  <div className="flex items-baseline gap-1.5 md:flex-col-reverse md:items-start md:gap-1">
    <span
      className={cn(
        "font-onest text-title font-bold leading-none tabular-nums",
        accent ? "text-[color:var(--aqt-teal)]" : "text-[color:var(--aqt-fg)]"
      )}
    >
      {value}
    </span>
    <span className="text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-muted)]">
      {label}
    </span>
  </div>
);

/**
 * A page HEADER, not a landing block: title, one sentence and the counters in
 * one compact band, so the first row of cards is on screen without scrolling.
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
      compact
      eyebrow={
        workspaceName ? (
          <span className="text-caption text-[color:var(--aqt-fg-muted)]">{workspaceName}</span>
        ) : null
      }
      title={t("tournamentsList.hero.title")}
      lede={t("tournamentsList.hero.lede")}
      aside={
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2 md:gap-x-8">
          {liveEvents > 0 ? (
            <Stat
              accent
              label={
                <span className="inline-flex items-center gap-1.5">
                  <StatusDot className="text-[color:var(--aqt-status-live)] [animation:aqtPulse_2s_ease-in-out_infinite] motion-reduce:animate-none" />
                  {t("tournamentsList.hero.liveNow")}
                </span>
              }
              value={liveEvents}
            />
          ) : null}
          {/* Numbers go through the locale formatter: the raw value used to render
              `1164` beside an ICU-formatted `1,453` in the very next tile. */}
          <Stat label={t("common.playersLabel")} value={format.number(totalPlayers)} />
          <Stat
            label={t("tournamentsList.hero.teamsBalancedLabel")}
            value={format.number(totalTeams)}
          />
        </div>
      }
    />
  );
};

export default TournamentsHero;
