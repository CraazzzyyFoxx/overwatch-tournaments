"use client";

import Image from "next/image";

import { ROLE_ACCENTS } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { Hero } from "@/types/hero.types";

interface HeroPickerBlockProps {
  /** Heroes to offer — pre-filtered to the role's class, or all heroes for Flex. */
  heroes: Hero[];
  /** Selected hero slugs in priority order (1 = top pick). */
  selected: string[];
  /** Maximum number of heroes selectable. */
  max: number;
  /** Role code used for accent styling. */
  roleCode: string;
  onChange: (slugs: string[]) => void;
}

export function HeroPickerBlock({ heroes, selected, max, roleCode, onChange }: HeroPickerBlockProps) {
  const accent = ROLE_ACCENTS[roleCode] ?? ROLE_ACCENTS.flex;
  const atMax = selected.length >= max;

  const toggle = (slug: string) => {
    const index = selected.indexOf(slug);
    if (index >= 0) {
      onChange(selected.filter((entry) => entry !== slug));
      return;
    }
    if (atMax) {
      return;
    }
    onChange([...selected, slug]);
  };

  return (
    <div className="flex flex-wrap gap-1.5">
      {heroes.map((hero) => {
        const index = selected.indexOf(hero.slug);
        const isSelected = index >= 0;
        const disabled = !isSelected && atMax;

        return (
          <button
            key={hero.slug}
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              toggle(hero.slug);
            }}
            disabled={disabled}
            aria-pressed={isSelected}
            title={hero.name}
            className={cn(
              "relative size-9 shrink-0 rounded-lg border transition-all",
              isSelected
                ? accent.selectedCard
                : disabled
                  ? "cursor-default border-white/8 opacity-35"
                  : "border-white/10 opacity-80 hover:border-white/20 hover:opacity-100",
            )}
          >
            <span className="block size-full overflow-hidden rounded-[7px]">
              <Image
                src={hero.image_path}
                alt={hero.name}
                width={36}
                height={36}
                className="size-full object-contain"
              />
            </span>
            {isSelected && (
              <span className="absolute -right-1 -top-1 flex size-4 items-center justify-center rounded-full bg-white text-[10px] font-bold leading-none text-black shadow">
                {index + 1}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
