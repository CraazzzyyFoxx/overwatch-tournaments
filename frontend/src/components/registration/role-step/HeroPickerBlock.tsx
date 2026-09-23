"use client";

import Image from "next/image";

import { ROLE_ACCENTS } from "@/lib/roster/roles";
import { cn } from "@/lib/utils";
import type { Hero } from "@/types/hero.types";

interface HeroPickerBlockProps {
  /** Heroes to offer — pre-filtered to the role's class. */
  heroes: Hero[];
  /** Selected hero slugs in priority order (1 = top pick). */
  selected: string[];
  /** Maximum number of heroes selectable. */
  max: number;
  /** Role code used for accent styling. */
  roleCode: string;
  onChange: (slugs: string[]) => void;
}

export function HeroPickerBlock({ heroes, selected, max, roleCode, onChange }: Readonly<HeroPickerBlockProps>) {
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
        // At the cap, unselected heroes stay focusable and announce their state:
        // `disabled` silently removed ~40 controls from the tab order with only
        // a counter to explain it.
        const blocked = !isSelected && atMax;

        return (
          <button
            key={hero.slug}
            type="button"
            aria-disabled={blocked}
            aria-pressed={isSelected}
            title={hero.name}
            onClick={(event) => {
              event.stopPropagation();
              toggle(hero.slug);
            }}
            className={cn(
              "relative size-9 shrink-0 rounded-lg border transition-[opacity,border-color]",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
              isSelected
                ? accent.selectedCard
                : blocked
                  ? "cursor-default border-[color:var(--aqt-border)] opacity-35"
                  : "border-[color:var(--aqt-border-2)] opacity-80 hover:border-[color:var(--aqt-border-3)] hover:opacity-100",
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
              <span className="absolute -right-1 -top-1 flex size-4 items-center justify-center rounded-full bg-[color:var(--aqt-teal)] text-label font-bold leading-none tabular-nums text-[color:var(--aqt-bg)] shadow">
                {index + 1}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
