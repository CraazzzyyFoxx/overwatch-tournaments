"use client";

import Image from "next/image";
import { useState } from "react";
import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import type { Hero } from "@/types/hero.types";

import { HeroPickerBlock } from "./HeroPickerBlock";

/** Avatars shown on the closed trigger before it falls back to a bare count. */
const PREVIEW_LIMIT = 3;

interface HeroPickerCellProps {
  roleCode: string;
  roleLabel: string;
  /** Heroes to offer — pre-filtered to the role's class. */
  heroes: Hero[];
  selected: string[];
  max: number;
  onChange: (slugs: string[]) => void;
  /** Skipped roles keep the cell in place, unusable — the matrix never reflows. */
  disabled?: boolean;
}

/**
 * Top-heroes cell for one matrix row.
 *
 * The roster used to be a ~40-tile wrap grid rendered inline, once per selected
 * role, so the role step grew by hundreds of nodes as the registrant picked
 * roles. Behind a popover the row keeps the same height whether 0 or `max`
 * heroes are chosen.
 */
export function HeroPickerCell({
  roleCode,
  roleLabel,
  heroes,
  selected,
  max,
  onChange,
  disabled = false,
}: Readonly<HeroPickerCellProps>) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const atMax = selected.length >= max;

  const preview = selected
    .slice(0, PREVIEW_LIMIT)
    .map((slug) => heroes.find((hero) => hero.slug === slug))
    .filter((hero): hero is Hero => hero !== undefined);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          aria-label={t("registration.roles.matrix.heroesLabel", {
            role: roleLabel,
            count: selected.length,
            max,
          })}
          className={cn(
            "flex h-9 w-full items-center gap-2 rounded-lg border border-[color:var(--aqt-border-2)]",
            "bg-[color:var(--aqt-overlay-2)] px-2 text-label font-medium transition-colors",
            "hover:bg-[color:var(--aqt-overlay-3)] disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-[color:var(--aqt-overlay-2)]",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
            selected.length > 0
              ? "text-[color:var(--aqt-fg)]"
              : "text-[color:var(--aqt-fg-muted)]",
          )}
        >
          {preview.length > 0 ? (
            <span className="flex shrink-0 items-center gap-1">
              {preview.map((hero) => (
                <span
                  key={hero.slug}
                  className="block size-6 overflow-hidden rounded-md border border-[color:var(--aqt-border-2)]"
                >
                  <Image
                    src={hero.image_path}
                    alt=""
                    width={24}
                    height={24}
                    className="size-full object-contain"
                  />
                </span>
              ))}
            </span>
          ) : (
            <Plus className="size-3.5 shrink-0" aria-hidden />
          )}
          <span className="ml-auto shrink-0 tabular-nums text-[color:var(--aqt-fg-muted)]">
            {t("registration.roles.topHeroes.count", { count: selected.length, max })}
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        aria-label={t("registration.roles.matrix.heroesPickerLabel", { role: roleLabel })}
        className="w-[min(22rem,calc(100vw-2rem))] space-y-2 p-3"
      >
        <p className="text-label font-medium uppercase tracking-label text-[color:var(--aqt-fg-muted)]">
          {roleLabel}
        </p>
        <HeroPickerBlock
          heroes={heroes}
          selected={selected}
          max={max}
          roleCode={roleCode}
          onChange={onChange}
        />
        {/* `block`: <output> is inline, so the popover's `space-y-2` rhythm
            would skip it. */}
        <output className="block text-label leading-4 text-[color:var(--aqt-fg-muted)]">
          {atMax
            ? t("registration.roles.matrix.heroesAtMax", { max })
            : t("registration.roles.topHeroes.desc", { max })}
        </output>
      </PopoverContent>
    </Popover>
  );
}
