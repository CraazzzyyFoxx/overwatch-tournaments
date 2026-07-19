import React from "react";
import { getTranslations } from "next-intl/server";
import { Star } from "lucide-react";
import Link from "next/link";
import { HeroPlaytime } from "@/types/hero.types";
import { CardSurface, normalizeRole } from "@/app/(site)/users/components/shared/atoms";
import HeroImage from "@/components/hero/HeroImage";
import HeroUserStatsPopover from "@/components/hero/HeroUserStatsPopover";

interface Props {
  heroes: HeroPlaytime[];
  userSlug: string;
  totalCount: number;
  limit?: number;
}

// playtime from the profile API is a normalized share in [0, 1].
const formatShare = (share: number): string => `${(share * 100).toFixed(0)}%`;

// Role-spectrum fill for the playtime track (design-book §3f — role-tinted,
// not the raw hero accent colour).
const roleFill = (hero: HeroPlaytime["hero"]): string => {
  const role = normalizeRole(hero.type ?? hero.role) ?? "damage";
  return `linear-gradient(90deg, color-mix(in srgb, var(--aqt-${role}) 55%, transparent), var(--aqt-${role}))`;
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
      <div className="flex flex-col gap-2.5 py-0.5">
        {top.map((hp) => {
          const widthPct = Math.max(3, (hp.playtime / (maxPlay || 1)) * 100);
          return (
            <div key={hp.hero.id} className="grid grid-cols-[26px_minmax(0,1fr)] items-center gap-2.5">
              <HeroImage
                hero={hp.hero}
                size="sm"
                title={hp.hero.name}
                popover={<HeroUserStatsPopover hero={hp.hero} playtimeShare={hp.playtime} />}
              />
              <div className="min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-[13px] font-semibold text-[color:var(--aqt-fg)]">{hp.hero.name}</span>
                  <span className="aqt-mono shrink-0 text-[12px] text-[color:var(--aqt-fg-muted)]">
                    {formatShare(hp.playtime)}
                  </span>
                </div>
                <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-[color:var(--aqt-card-2)]">
                  <div className="h-full rounded-full" style={{ width: `${widthPct}%`, background: roleFill(hp.hero) }} />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </CardSurface>
  );
};

export default OverviewMostPlayedHeroes;
