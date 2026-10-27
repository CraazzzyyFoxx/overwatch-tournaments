"use client";

import { useLocale, useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import { BackLink } from "@/components/site/BackLink";
import { HeroFrame, HeroStat } from "@/components/site/PageHero";
import { AchievementArt } from "@/components/achievements/AchievementArt";
import { Badge } from "@/components/ui/badge";
import type { Achievement } from "@/types/achievement.types";
import { classifyRarity, localizedText } from "@/lib/achievements/rarity";

/** Detail-page identity banner: rarity-framed crest, name, description, tags
 *  and two figures. The rarity tint is inherited from `--rar` on the page root. */
const AchievementDetailHeader = ({ achievement }: { achievement: Achievement }) => {
  const t = useTranslations();
  const locale = useLocale();
  const format = useFormatter();
  const holders = achievement.count ?? 0;
  const description = localizedText(locale, achievement.description_ru, achievement.description_en);

  return (
    <HeroFrame>
      <div className="flex flex-col gap-7 px-6 py-8 md:px-10 md:py-9 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 flex-col gap-5 sm:flex-row sm:items-start">
          <AchievementArt
            achievement={achievement}
            sizes="132px"
            className="aspect-square w-[clamp(96px,12vw,132px)] shrink-0 rounded-2xl border border-[hsl(var(--rar)/0.5)] ring-1 ring-[hsl(var(--rar)/0.14)]"
          />

          <div className="flex min-w-0 flex-col gap-3">
            <BackLink href="/achievements" className="self-start">
              {t("achievements.detail.backToCatalog")}
            </BackLink>

            <h1 className="font-onest text-[clamp(1.7rem,3.4vw,2.6rem)] font-semibold leading-[1.05] tracking-[-0.01em] text-[color:var(--aqt-fg)]">
              {achievement.name}
            </h1>

            {description ? (
              <p className="max-w-[42rem] text-sm leading-relaxed text-[color:var(--aqt-fg-muted)]">
                {description}
              </p>
            ) : null}

            <div className="mt-1 flex flex-wrap items-center gap-2">
              {holders > 0 ? (
                <Badge
                  shape="pill"
                  className="border-[hsl(var(--rar)/0.4)] bg-[hsl(var(--rar)/0.08)] font-semibold text-[hsl(var(--rar))]"
                >
                  {t(`achievements.rarityName.${classifyRarity(achievement.rarity * 100)}`)}
                </Badge>
              ) : null}
              {achievement.category ? (
                <Badge variant="secondary" shape="pill">
                  {t(`achievements.category.${achievement.category}`)}
                </Badge>
              ) : null}
              {achievement.scope ? (
                <Badge variant="secondary" shape="pill">
                  {t(`achievements.scope.${achievement.scope}`)}
                </Badge>
              ) : null}
            </div>
          </div>
        </div>

        <div className="flex shrink-0 gap-x-10 gap-y-5 border-t border-[color:var(--aqt-border)] pt-6 lg:border-t-0 lg:border-l lg:pt-0 lg:pl-10">
          {holders > 0 ? (
            <HeroStat
              label={t("achievements.detail.rarity")}
              value={<span className="text-[hsl(var(--rar))]">{(achievement.rarity * 100).toFixed(2)}%</span>}
            />
          ) : null}
          <HeroStat label={t("common.playersLabel")} value={format.number(holders)} />
        </div>
      </div>
    </HeroFrame>
  );
};

export default AchievementDetailHeader;
