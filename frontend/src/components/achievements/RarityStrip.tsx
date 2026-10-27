"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { RowButton } from "@/components/ui/row-button";
import { cn } from "@/lib/utils";
import { RARITY_ORDER, rarityRanges, rarityVarClass, type Rarity } from "@/lib/achievements/rarity";

interface RarityStripProps {
  /** Big figure per tier (a count, or "earned / total"). */
  values: Record<Rarity, ReactNode>;
  active: Rarity | null;
  onToggle: (rarity: Rarity | null) => void;
  className?: string;
}

/**
 * The rarity distribution, doubling as the rarity filter: one pressable cell per
 * tier, tier hue on the leading edge only. Pressing the active tier clears it.
 * Tints come from `--rar`, set per tier by `rarityVarClass` (`lib/achievements/rarity.ts`).
 */
export function RarityStrip({ values, active, onToggle, className }: RarityStripProps) {
  const t = useTranslations();
  const ranges = rarityRanges(t);

  return (
    <div
      role="group"
      aria-label={t("achievements.rarityFilter")}
      className={cn(
        "grid grid-cols-3 gap-px overflow-hidden rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-border)] lg:grid-cols-6",
        className
      )}
    >
      {RARITY_ORDER.map((r) => {
        const pressed = active === r;
        return (
          <RowButton
            key={r}
            aria-pressed={pressed}
            onClick={() => onToggle(pressed ? null : r)}
            className={cn(
              rarityVarClass(r),
              "relative flex flex-col gap-1.5 bg-[color:var(--aqt-card)] py-3 pr-3 pl-5 transition-[background-color,opacity] duration-150 focus-visible:z-[1]",
              "before:absolute before:top-3 before:bottom-3 before:left-0 before:w-[3px] before:rounded-r-sm before:bg-[hsl(var(--rar))]",
              pressed && "bg-[hsl(var(--rar)/0.08)] hover:bg-[hsl(var(--rar)/0.12)]",
              active && !pressed && "opacity-50 hover:opacity-80"
            )}
          >
            <span className={cn("text-label font-semibold", pressed ? "text-[hsl(var(--rar))]" : "text-[color:var(--aqt-fg-muted)]")}>
              {t(`achievements.rarityName.${r}`)}
            </span>
            <span className="font-onest text-title font-bold leading-none tabular-nums text-[color:var(--aqt-fg)]">
              {values[r]}
            </span>
            <span className="aqt-tnum text-label text-[color:var(--aqt-fg-dim)]">{ranges[r]}</span>
          </RowButton>
        );
      })}
    </div>
  );
}
