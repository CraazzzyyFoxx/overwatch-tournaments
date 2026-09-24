import { getTranslations } from "next-intl/server";
import { ArrowRight, Award } from "lucide-react";
import Image from "next/image";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { AchievementRarity } from "@/types/achievement.types";
import { CardSurface } from "@/app/(site)/users/components/shared/atoms";
import {
  classifyRarity,
  rarityVarClass,
  type Rarity
} from "@/app/(site)/users/components/achievements/rarity";

interface Props {
  achievements: AchievementRarity[];
  userSlug: string;
  limit?: number;
}

const DEFAULT_LIMIT = 4;

// Compact, localized tier name used as the rarity label on each card.
const TIER_LABEL_KEY: Record<Rarity, string> = {
  mythic: "users.overview.achievementsPreview.tier.mythic",
  legendary: "users.overview.achievementsPreview.tier.legendary",
  epic: "users.overview.achievementsPreview.tier.epic",
  rare: "users.overview.achievementsPreview.tier.rare",
  uncommon: "users.overview.achievementsPreview.tier.uncommon",
  common: "users.overview.achievementsPreview.tier.common"
};

const OverviewAchievementsPreview = async ({ achievements, userSlug, limit = DEFAULT_LIMIT }: Props) => {
  // count === 0 is a not-yet-earned (locked) entry — preview only real unlocks.
  const unlocked = achievements.filter((a) => a.count > 0);
  if (unlocked.length === 0) return null;

  const t = await getTranslations();

  // Rarest first (lower fraction = rarer), then most-earned.
  const top = [...unlocked]
    .sort((a, b) => a.rarity - b.rarity || b.count - a.count)
    .slice(0, limit);

  return (
    <CardSurface
      title={t("users.overview.achievementsPreview.title")}
      icon={<Award size={15} />}
      action={
        <HoverPrefetchLink href={`/users/${userSlug}?tab=achievements`} className="aqt-seeall">
          {t("common.all")} {unlocked.length}
          <ArrowRight aria-hidden className="size-3" />
        </HoverPrefetchLink>
      }
    >
      <div className="flex flex-col gap-2">
        {top.map((ach) => {
          const rarity = classifyRarity(ach.rarity * 100);
          const rarityLabel = t(TIER_LABEL_KEY[rarity] as Parameters<typeof t>[0]);
          const imgSrc = ach.image_url ?? `/achievements/${ach.slug}.webp`;
          return (
            <div
              key={ach.id}
              className={`${rarityVarClass(rarity)} flex items-center gap-3 rounded-[10px] border px-3 py-2.5`}
              style={{
                borderColor: "hsl(var(--rar) / 0.3)",
                background: "hsl(var(--rar) / 0.06)"
              }}
            >
              <div
                className="relative h-10 w-10 shrink-0 overflow-hidden rounded-[9px] border"
                style={{ borderColor: "hsl(var(--rar) / 0.4)", background: "hsl(var(--rar) / 0.16)" }}
              >
                <Image src={imgSrc} alt={ach.name} fill sizes="40px" className="object-cover" />
              </div>
              <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <div className="truncate text-caption font-semibold text-[color:var(--aqt-fg)]" title={ach.name}>
                  {ach.name}
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className="aqt-tnum text-label font-bold uppercase tracking-label"
                    style={{ color: "hsl(var(--rar))" }}
                  >
                    <span aria-hidden>◆</span> {rarityLabel}
                  </span>
                  <span className="aqt-tnum text-label text-[color:var(--aqt-fg-dim)]">
                    {(ach.rarity * 100).toFixed(2)}%
                  </span>
                </div>
              </div>
              {ach.count > 1 ? (
                <span className="aqt-tnum text-label font-bold text-[color:var(--aqt-fg-muted)]">×{ach.count}</span>
              ) : null}
            </div>
          );
        })}
      </div>
    </CardSurface>
  );
};

export default OverviewAchievementsPreview;
