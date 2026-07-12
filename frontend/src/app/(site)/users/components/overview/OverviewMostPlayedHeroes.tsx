import React from "react";
import { getTranslations } from "next-intl/server";
import { Star } from "lucide-react";
import Link from "next/link";
import { HeroPlaytime } from "@/types/hero.types";
import { CardSurface } from "@/app/(site)/users/components/shared/atoms";
import HeroImage from "@/components/hero/HeroImage";
import HeroUserStatsPopover from "@/components/hero/HeroUserStatsPopover";

interface Props {
  heroes: HeroPlaytime[];
  userSlug: string;
  totalCount: number;
  limit?: number;
}

// playtime from the profile API is a normalized share in [0, 1]
const formatShare = (share: number): string => `${(share * 100).toFixed(0)}%`;

const FALLBACK_COLOR = "#d4506b";

const heroBarBackground = (color: string | null | undefined): string => {
  const base = color && color.startsWith("#") ? color : FALLBACK_COLOR;
  // Light-to-dark gradient based on the hero accent color
  return `linear-gradient(90deg, ${base}, ${base}aa)`;
};

const OverviewMostPlayedHeroes = async ({ heroes, userSlug, totalCount, limit = 9 }: Props) => {
  if (heroes.length === 0) return null;

  const t = await getTranslations();
  const top = heroes.slice(0, limit);
  const maxPlay = top[0]?.playtime ?? 1;

  return (
    <CardSurface
      title={t("users.overview.mostPlayed.title")}
      icon={<Star size={15} />}
      action={
        <Link href={`/users/${userSlug}?tab=heroes`} className="aqt-seeall">
          {t("common.all")} {totalCount} →
        </Link>
      }
    >
      <div className="flex flex-col gap-2 py-0.5">
        {top.map((hp) => {
          const widthPct = (hp.playtime / maxPlay) * 100;
          return (
            <div key={hp.hero.id} className="grid grid-cols-[30px_1fr_64px] items-center gap-2.5">
              <HeroImage
                hero={hp.hero}
                size="md"
                title={hp.hero.name}
                bare
                popover={<HeroUserStatsPopover hero={hp.hero} playtimeShare={hp.playtime} />}
              />
              <div
                className="relative h-5 cursor-pointer overflow-hidden rounded-[5px] transition-[filter] hover:brightness-110"
                style={{ width: `${widthPct}%`, background: heroBarBackground(hp.hero.color) }}
                title={`${hp.hero.name} · ${formatShare(hp.playtime)}`}
              />
              <span className="aqt-mono text-right text-[12px] text-[color:var(--aqt-fg-muted)]">
                {formatShare(hp.playtime)}
              </span>
            </div>
          );
        })}
      </div>
    </CardSurface>
  );
};

export default OverviewMostPlayedHeroes;
