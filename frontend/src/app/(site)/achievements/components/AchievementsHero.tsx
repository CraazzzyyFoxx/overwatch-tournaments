"use client";

import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import { PageHero, HeroCoord, HeroStat } from "@/components/site/PageHero";
import { classifyRarity, rarityVarClass } from "@/lib/achievements/rarity";
import { cn } from "@/lib/utils";

interface AchievementsHeroProps {
  workspaceName?: string | null;
  total: number;
  /** Share (percent) of players holding the rarest achievement anyone holds; null when none is earned. */
  rarestPct: number | null;
  /** Earned (player, achievement) pairs: the sum of holders across the catalog. */
  unlocks: number;
}

/** Same hero shape as the other top-level pages (see TournamentsHero). */
const AchievementsHero = ({ workspaceName, total, rarestPct, unlocks }: AchievementsHeroProps) => {
  const t = useTranslations();
  const format = useFormatter();

  return (
    <PageHero
      eyebrow={workspaceName ? <HeroCoord>{workspaceName}</HeroCoord> : null}
      title={t("achievements.hero.title")}
      lede={t("achievements.hero.lede")}
      aside={
        <div className="flex flex-wrap gap-x-8 gap-y-5 lg:justify-end">
          <HeroStat label={t("achievements.stats.total")} value={format.number(total)} />
          {rarestPct !== null ? (
            <HeroStat
              label={t("achievements.stats.rarest")}
              value={
                <span className={cn(rarityVarClass(classifyRarity(rarestPct)), "text-[hsl(var(--rar))]")}>
                  {rarestPct.toFixed(2)}%
                </span>
              }
            />
          ) : null}
          <HeroStat label={t("achievements.stats.unlocks")} value={format.number(unlocks)} />
        </div>
      }
    />
  );
};

export default AchievementsHero;
