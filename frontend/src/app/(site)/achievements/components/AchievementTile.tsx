"use client";

import Link from "next/link";
import { Users } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { AchievementArt } from "@/components/achievements/AchievementArt";
import { Card } from "@/components/ui/card";
import { GameLabel } from "@/components/workspace/GameLabel";
import { cn } from "@/lib/utils";
import { classifyRarity, localizedText, rarityVarClass } from "@/lib/achievements/rarity";
import type { Achievement } from "@/types/achievement.types";
import type { DisciplineDescriptor } from "@/types/discipline.types";

/**
 * Image-forward catalog tile: the badge art is the hero, the name and the two
 * numbers that matter (share of players, players holding it) always sit on the
 * bottom scrim, so nothing essential is hover-only. Hover/focus additionally
 * reveals the description. The whole tile is one link to the detail page.
 */
const AchievementTile = ({
  achievement,
  games
}: {
  achievement: Achievement;
  /** Installed games by code, passed only when the catalogue spans several games (spec §6.1). */
  games?: Map<string, DisciplineDescriptor>;
}) => {
  const t = useTranslations();
  const locale = useLocale();
  const holders = achievement.count ?? 0;
  const description = localizedText(locale, achievement.description_ru, achievement.description_en);

  return (
    <Card
      asChild
      className={cn(
        "group/tile relative isolate block aspect-square overflow-hidden transition-colors duration-150 hover:border-[color:var(--aqt-teal)] focus-visible:border-[color:var(--aqt-teal)] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none",
        // The rarity hairline along the top edge.
        "before:absolute before:inset-x-0 before:top-0 before:z-3 before:h-0.5 before:bg-linear-to-r before:from-[hsl(var(--rar))] before:to-[hsl(var(--rar)/0.15)]",
        // Unearned rules sit at 0% and would read as mythic; they stay neutral.
        rarityVarClass(holders > 0 ? classifyRarity(achievement.rarity * 100) : "common")
      )}
    >
      <Link href={`/achievements/${achievement.id}`}>
        <AchievementArt
          achievement={achievement}
          sizes="(min-width: 1536px) 14vw, (min-width: 1024px) 20vw, (min-width: 640px) 25vw, 50vw"
          className="absolute inset-0"
        />

        {/* Hover/focus reveal: over the art, under the foot. */}
        {description ? (
          <span
            aria-hidden
            className="absolute inset-0 z-1 flex items-center justify-center bg-[color:color-mix(in_srgb,var(--aqt-bg)_84%,transparent)] px-3.5 pt-3.5 pb-16 text-center opacity-0 transition-opacity duration-150 group-hover/tile:opacity-100 group-focus-visible/tile:opacity-100 motion-reduce:transition-none"
          >
            <span className="line-clamp-5 text-caption text-[color:var(--aqt-fg)]">{description}</span>
          </span>
        ) : null}

        {/* Bottom scrim: name and the two numbers, always visible. */}
        <span className="absolute inset-x-0 bottom-0 z-2 flex flex-col gap-1 bg-linear-to-b from-transparent to-[color:color-mix(in_srgb,var(--aqt-bg)_88%,transparent)] to-62% px-2.5 pt-7 pb-2.25">
          <span className="line-clamp-2 font-display text-caption leading-tight font-bold text-[color:var(--aqt-fg)]">
            {achievement.name}
          </span>
          <span
            data-tile-meta
            className="flex items-center justify-between gap-2 font-[family-name:var(--aqt-data)] text-label font-bold text-[color:var(--aqt-fg-muted)]"
          >
            {games ? <GameLabel code={achievement.discipline} games={games} /> : null}
            {holders > 0 ? (
              <>
                <span className="text-[hsl(var(--rar))] tabular-nums">{(achievement.rarity * 100).toFixed(2)}%</span>
                <span
                  className="inline-flex items-center gap-1 tabular-nums"
                  aria-label={t("achievements.holders", { count: holders })}
                >
                  <Users aria-hidden className="size-3" />
                  {holders}
                </span>
              </>
            ) : (
              <span>{t("achievements.notEarned.tile")}</span>
            )}
          </span>
        </span>
      </Link>
    </Card>
  );
};

export default AchievementTile;
