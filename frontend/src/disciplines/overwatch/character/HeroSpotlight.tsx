"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { signedPoints } from "@/components/profile/CharacterCard";
import { CardSurface, ProfileStat } from "@/components/profile/atoms";
import { characterClass } from "@/lib/catalog/attrs";
import { LOW_SAMPLE_GAMES, winrateColor } from "@/lib/colors";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import { formatSeconds } from "@/lib/format";
import type { CharacterWithUserStats } from "@/types/user.types";
import type { DisciplineMetadata } from "@/types/discipline.types";

import { LogStatsName } from "../stat-names";
import { useHeroClass } from "./classes";
import HeroRadar from "./HeroRadar";
import type { RadarAxis } from "./hero-stats";
import { computeDelta, deltaColor, formatDelta, formatStatValue, heroWinrate } from "./utils";

/**
 * The selected hero's band: who it is, with the tab's tournament filter in the top right corner; the outcome of
 * playing it — winrate, games, time and KDA; and its radar against the average under the filter. The per-10 figures
 * live in the comparison below it. Comparisons, the radar included, hide below `LOW_SAMPLE_GAMES`.
 */
const HeroSpotlight = ({
  hero,
  playtime,
  share,
  radar,
  filterSlot,
  metadata
}: {
  hero: CharacterWithUserStats;
  playtime: number;
  share: number;
  /** `null` without enough comparisons to draw a shape. */
  radar: RadarAxis[] | null;
  /** The tournament filter: it scopes the whole tab, this band's own figures included. */
  filterSlot?: ReactNode;
  metadata: DisciplineMetadata;
}) => {
  const t = useTranslations();
  const format = useFormatter();
  const heroClass = useHeroClass(metadata);
  const cls = characterClass(hero.character);
  const lowSample = hero.games < LOW_SAMPLE_GAMES;
  const winrate = heroWinrate(hero);
  const winrateVs =
    !lowSample && winrate != null && hero.win_rate_all != null ? signedPoints(winrate - hero.win_rate_all) : null;
  const kda = hero.stats.find((stat) => stat.name === LogStatsName.KDA);
  const kdaDelta = kda && !lowSample ? computeDelta(kda.avg_10, kda.avg_10_all, false) : null;

  return (
    <CardSurface>
      {/* One grid, so the filter keeps one place in the DOM: under the name on a phone, in the band's top right corner
          from sm, and above the radar from lg. */}
      <div className="grid gap-x-8 gap-y-4 sm:grid-cols-[minmax(0,1fr)_auto]">
        <div className="flex min-w-0 items-center gap-4">
          <CatalogEntityImage entity={hero.character} size={56} rounded="lg" decorative />
          <div className="flex min-w-0 flex-col gap-1">
            <h2 className="aqt-display m-0 truncate text-title font-bold text-[color:var(--aqt-fg)]">
              {hero.character.name}
            </h2>
            {cls ? (
              <span className="inline-flex items-center gap-1.5 text-caption" style={{ color: heroClass.color(cls) }}>
                {heroClass.icon(cls, 14)}
                <span className="text-[color:var(--aqt-fg-muted)]">{heroClass.label(cls)}</span>
              </span>
            ) : null}
          </div>
        </div>
        {filterSlot ? <div className="sm:self-center sm:justify-self-end">{filterSlot}</div> : null}

        {/* Beside the radar the figures sit two by two, so they hold its height instead of one thin row. */}
        <div
          className={cn(
            "grid grid-cols-2 gap-x-8 gap-y-4 sm:col-span-2 sm:grid-cols-4",
            radar && "lg:col-span-1 lg:max-w-xl lg:grid-cols-2 lg:self-center"
          )}
        >
          <ProfileStat
            size="md"
            label={t("users.heroes.quick.winrate")}
            value={winrate == null ? "—" : `${(winrate * 100).toFixed(0)}%`}
            color={winrate == null ? undefined : winrateColor(winrate * 100, lowSample)}
          >
            {winrateVs ? (
              <span className="aqt-tnum text-label font-bold" style={{ color: winrateVs.color }}>
                {t("users.heroes.card.vsAvg", { value: winrateVs.text })}
              </span>
            ) : null}
          </ProfileStat>
          <ProfileStat
            size="md"
            label={t("users.heroes.games")}
            value={hero.games}
            sub={`${hero.win}–${hero.loss}–${hero.draw}`}
            title={t("users.heroes.wld")}
          />
          <ProfileStat
            size="md"
            label={t("matches.stat.heroTimePlayed")}
            value={formatSeconds(playtime)}
            sub={t("users.heroes.poolShare", { pct: (share * 100).toFixed(0) })}
          />
          <ProfileStat
            size="md"
            label={t("users.heroes.quick.kda")}
            value={kda ? formatStatValue(format, kda.name, kda.avg_10) : "—"}
          >
            {kdaDelta == null ? null : (
              <span className="aqt-tnum text-label font-bold" style={{ color: deltaColor(kdaDelta) }}>
                {t("users.heroes.card.vsAvg", { value: formatDelta(kdaDelta) })}
              </span>
            )}
          </ProfileStat>
        </div>

        {radar ? (
          <div className="justify-self-center sm:col-span-2 lg:col-span-1 lg:justify-self-end">
            <HeroRadar heroName={hero.character.name} axes={radar} />
          </div>
        ) : null}
      </div>
    </CardSurface>
  );
};

export default HeroSpotlight;
