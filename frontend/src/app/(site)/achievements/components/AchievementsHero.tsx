"use client";

import React from "react";
import { useTranslations } from "next-intl";

import { PageHero, HeroCoord, HeroStat } from "@/components/site/PageHero";

interface AchievementsHeroProps {
  workspaceName?: string | null;
  total: number;
  rarestPct: number;
  totalEarned: number;
  mythicCount: number;
}

const AchievementsHero = ({
  workspaceName,
  total,
  rarestPct,
  totalEarned,
  mythicCount
}: AchievementsHeroProps) => {
  const t = useTranslations();

  return (
    <PageHero
      eyebrow={
        <>
          <HeroCoord>{t("achievements.hero.coord")}</HeroCoord>
          {workspaceName ? (
            <HeroCoord>{t("tournamentsList.hero.sector", { name: workspaceName })}</HeroCoord>
          ) : null}
        </>
      }
      title={t.rich("achievements.hero.title", { em: (chunks) => <em>{chunks}</em> })}
      lede={t("achievements.hero.lede")}
      aside={
        <div className="grid grid-cols-3 gap-6">
          <HeroStat
            label={t("achievements.stats.total")}
            value={total}
            sub={t("achievements.hero.mythicCount", { count: mythicCount })}
          />
          <HeroStat
            label={t("achievements.stats.rarest")}
            value={
              <span className="text-[color:var(--aqt-amber)]">{rarestPct.toFixed(2)}%</span>
            }
            sub={t("achievements.hero.rarestSub")}
          />
          <HeroStat
            label={t("achievements.stats.totalEarned")}
            value={totalEarned.toLocaleString()}
            sub={t("achievements.hero.earnedSub")}
          />
        </div>
      }
    />
  );
};

export default AchievementsHero;
