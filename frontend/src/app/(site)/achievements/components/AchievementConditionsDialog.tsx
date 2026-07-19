"use client";

import React from "react";
import Image from "next/image";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import type { Achievement } from "@/types/achievement.types";
import { classifyRarity, rarityVarClass } from "@/app/(site)/users/components/achievements/rarity";
import ConditionTreeView from "@/app/(site)/achievements/components/ConditionTreeView";

interface Props {
  achievement: Achievement | null;
  onClose: () => void;
}

/** How-to-earn dialog: badge identity + tags + the condition tree that the
 *  achievement engine evaluates. Opened from a tile's rules button. */
const AchievementConditionsDialog = ({ achievement, onClose }: Props) => {
  const t = useTranslations();
  const ach = achievement;
  const rarity = ach ? classifyRarity(ach.rarity * 100) : null;
  const imgSrc = ach ? ach.image_url ?? `/achievements/${ach.slug}.webp` : null;

  return (
    <Dialog open={!!ach} onOpenChange={(open) => !open && onClose()}>
      {ach ? (
        <DialogContent
          className={cn(
            "gap-0 border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)] p-0 sm:max-w-lg",
            rarity && rarityVarClass(rarity)
          )}
        >
          <DialogHeader className="flex-row items-start gap-3 space-y-0 border-b border-[color:var(--aqt-border)] p-5 text-left">
            <div className="aqt-ach-crest !w-14 !rounded-xl">
              {imgSrc ? (
                <Image src={imgSrc} alt={ach.name} fill sizes="56px" />
              ) : null}
            </div>
            <div className="flex min-w-0 flex-col gap-1.5">
              <DialogTitle className="text-base font-semibold leading-snug text-[color:var(--aqt-fg)]">
                {ach.name}
              </DialogTitle>
              <DialogDescription className="text-sm leading-relaxed text-[color:var(--aqt-fg-muted)]">
                {ach.description_ru || ach.description_en}
              </DialogDescription>
            </div>
          </DialogHeader>

          <div className="flex max-h-[60vh] flex-col gap-4 overflow-y-auto p-5">
            <div className="flex flex-wrap gap-2">
              <span className="aqt-meta-pill rar">{rarity}</span>
              <span className="aqt-meta-pill">
                {t("achievements.rarity", { percent: (ach.rarity * 100).toFixed(2) })}
              </span>
              {ach.category ? (
                <span className="aqt-meta-pill">{t(`achievements.category.${ach.category}`)}</span>
              ) : null}
              {ach.scope ? (
                <span className="aqt-meta-pill">{t(`achievements.scope.${ach.scope}`)}</span>
              ) : null}
            </div>

            <div className="flex flex-col gap-2">
              <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
                {t("achievements.conditionsTitle")}
              </div>
              <div className="rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] p-3">
                {ach.condition_tree ? (
                  <ConditionTreeView tree={ach.condition_tree} />
                ) : (
                  <span className="text-xs text-[color:var(--aqt-fg-dim)]">
                    {t("achievements.noConditionsDefined")}
                  </span>
                )}
              </div>
            </div>

            <Link
              href={`/achievements/${ach.id}`}
              onClick={onClose}
              className="inline-flex items-center gap-1 self-start text-[11px] font-bold uppercase tracking-[0.1em] text-[color:var(--aqt-teal)] transition-opacity hover:opacity-80"
            >
              {t("achievements.detail.viewEarners")}
              <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
            </Link>
          </div>
        </DialogContent>
      ) : null}
    </Dialog>
  );
};

export default AchievementConditionsDialog;
