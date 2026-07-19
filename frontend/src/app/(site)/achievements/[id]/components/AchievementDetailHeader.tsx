"use client";

import React from "react";
import Image from "next/image";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { useTranslations } from "next-intl";

import { HeroFrame, HeroCoord, HeroStat } from "@/components/site/PageHero";
import type { Achievement } from "@/types/achievement.types";
import { classifyRarity, rarityTitles } from "@/app/(site)/users/components/achievements/rarity";

interface Props {
  achievement: Achievement;
}

/** Detail-page identity banner: rarity-framed crest, name, description, tag
 *  pills and a compact stats trio. Rarity tint is inherited from `--rar` set
 *  on the page root, so this stays a plain presentational block. */
const AchievementDetailHeader = ({ achievement }: Props) => {
  const t = useTranslations();
  const rarity = classifyRarity(achievement.rarity * 100);
  const titles = rarityTitles(t);
  const imgSrc = achievement.image_url ?? `/achievements/${achievement.slug}.webp`;
  const description = achievement.description_ru || achievement.description_en;

  return (
    <HeroFrame>
      <div className="flex flex-col gap-7 px-6 py-8 md:px-10 md:py-9 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-start gap-5">
          <div className="aqt-ach-crest">
            <Image src={imgSrc} alt={achievement.name} fill sizes="132px" quality={100} />
          </div>

          <div className="flex min-w-0 flex-col gap-3">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
              <Link
                href="/achievements"
                className="inline-flex items-center gap-1.5 font-mono text-[12px] uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)] transition-colors hover:text-[color:var(--aqt-teal)]"
              >
                <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
                {t("achievements.detail.backToCatalog")}
              </Link>
              {achievement.category ? (
                <HeroCoord>{t(`achievements.category.${achievement.category}`)}</HeroCoord>
              ) : null}
            </div>

            <h1 className="font-onest text-[clamp(1.7rem,3.4vw,2.6rem)] font-semibold leading-[1.05] tracking-[-0.01em] text-[color:var(--aqt-fg)]">
              {achievement.name}
            </h1>

            {description ? (
              <p className="max-w-[42rem] text-sm leading-relaxed text-[color:var(--aqt-fg-muted)]">
                {description}
              </p>
            ) : null}

            <div className="mt-1 flex flex-wrap items-center gap-2">
              <span className="aqt-meta-pill rar">{titles[rarity]}</span>
              {achievement.scope ? (
                <span className="aqt-meta-pill">{t(`achievements.scope.${achievement.scope}`)}</span>
              ) : null}
            </div>
          </div>
        </div>

        <div className="grid shrink-0 grid-cols-2 gap-x-8 gap-y-5 border-t border-[color:var(--aqt-border)] pt-6 lg:border-l lg:border-t-0 lg:pl-10 lg:pt-0">
          <HeroStat
            label={t("achievements.stats.rarest")}
            value={
              <span className="aqt-rar-fg">{(achievement.rarity * 100).toFixed(2)}%</span>
            }
            sub={t("achievements.detail.rarityShare")}
          />
          <HeroStat
            label={t("achievements.stats.totalEarned")}
            value={(achievement.count ?? 0).toLocaleString()}
            sub={t("achievements.detail.timesAwarded")}
          />
        </div>
      </div>
    </HeroFrame>
  );
};

export default AchievementDetailHeader;
