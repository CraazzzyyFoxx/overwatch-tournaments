"use client";

import { useTranslations } from "next-intl";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { signedPoints } from "@/components/profile/CharacterCard";
import { CardSurface, ProfileStat } from "@/components/profile/atoms";
import { characterClass } from "@/lib/catalog/attrs";
import { LOW_SAMPLE_GAMES, winrateColor } from "@/lib/colors";
import { useFormatter } from "@/lib/datetime/client";
import { formatSeconds } from "@/lib/format";
import type { CharacterWithUserStats } from "@/types/user.types";
import type { DisciplineMetadata } from "@/types/discipline.types";

import { LogStatsName } from "../stat-names";
import { useHeroClass } from "./classes";
import { computeDelta, deltaColor, formatDelta, formatStatValue, heroWinrate } from "./utils";

/**
 * The selected hero's band: who it is, then the outcome of playing it — winrate, games, time and KDA. The per-10
 * figures live in the comparison below it, said once. Comparisons hide below `LOW_SAMPLE_GAMES`.
 */
const HeroSpotlight = ({
  hero,
  playtime,
  share,
  metadata
}: {
  hero: CharacterWithUserStats;
  playtime: number;
  share: number;
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
      <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between lg:gap-10">
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

        <div className="grid grid-cols-2 gap-x-8 gap-y-4 sm:grid-cols-4 lg:gap-x-10">
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
      </div>
    </CardSurface>
  );
};

export default HeroSpotlight;
