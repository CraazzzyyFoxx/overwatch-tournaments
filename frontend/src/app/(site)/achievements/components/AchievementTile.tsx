"use client";

import React from "react";
import Image from "next/image";
import Link from "next/link";
import { ScrollText } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { Achievement } from "@/types/achievement.types";
import { classifyRarity, rarityVarClass } from "@/app/(site)/users/components/achievements/rarity";

interface AchievementTileProps {
  achievement: Achievement;
  /** Opens the condition-tree dialog for this achievement, if it has one. */
  onViewRules: (achievement: Achievement) => void;
}

/**
 * Image-forward catalog tile: the badge art is the hero, framed in the
 * Editorial-Tactical language. A rarity hairline + mono numerals sit over a
 * legibility scrim; hover reveals the full description and the rarity chip.
 * The whole tile links to the detail page; the rules button is a sibling of
 * the overlay link (never nested) so both stay independently clickable.
 */
const AchievementTile = ({ achievement, onViewRules }: AchievementTileProps) => {
  const t = useTranslations();
  const rarity = classifyRarity(achievement.rarity * 100);
  const hasRules = Boolean(achievement.condition_tree);
  const imgSrc = achievement.image_url ?? `/achievements/${achievement.slug}.webp`;
  const description = achievement.description_ru || achievement.description_en;

  return (
    <div className={cn("aqt-ach-tile group", rarityVarClass(rarity))}>
      <Image
        src={imgSrc}
        alt={achievement.name}
        fill
        quality={100}
        sizes="(min-width: 1536px) 14vw, (min-width: 1024px) 20vw, (min-width: 640px) 25vw, 50vw"
        className="aqt-ach-tile__img"
      />

      <span aria-hidden className="aqt-ach-tile__scrim" />

      <div className="aqt-ach-tile__name">{achievement.name}</div>

      <span className="aqt-ach-tile__rarity">{(achievement.rarity * 100).toFixed(2)}%</span>

      {(achievement.count ?? 0) > 0 ? (
        <span className="aqt-ach-tile__count">×{achievement.count}</span>
      ) : null}

      {description ? (
        <div className="aqt-ach-tile__desc">
          <p>{description}</p>
        </div>
      ) : null}

      <Link
        href={`/achievements/${achievement.id}`}
        aria-label={achievement.name}
        className="absolute inset-0 z-[10]"
      />

      {hasRules ? (
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onViewRules(achievement);
          }}
          className="aqt-ach-tile__rules"
          aria-label={t("achievements.viewRules", { name: achievement.name })}
        >
          <ScrollText className="h-3.5 w-3.5" aria-hidden />
        </button>
      ) : null}
    </div>
  );
};

export default AchievementTile;
