"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Input } from "@craazzzyyfoxx/admin-kit/ui/input";

import type { RoleAccent } from "@/lib/registration/role-accent";
import { cn } from "@/lib/utils";
import type { CatalogEntityRead } from "@/types/catalog.types";

interface HeroPickerBlockProps {
  /** Characters to offer: the owner game's whole roster. */
  heroes: CatalogEntityRead[];
  /** Selected hero slugs in priority order (1 = top pick). */
  selected: string[];
  /** Maximum number of heroes selectable. */
  max: number;
  /** The role's accent, for the selected tiles. */
  accent: RoleAccent;
  onChange: (slugs: string[]) => void;
}

/** Past this many characters the roster is searched by name instead of scanned. */
const SEARCH_THRESHOLD = 24;

export function HeroPickerBlock({ heroes, selected, max, accent, onChange }: Readonly<HeroPickerBlockProps>) {
  const t = useTranslations("registration.roles.topHeroes");
  const [query, setQuery] = useState("");
  const atMax = selected.length >= max;
  const needle = query.trim().toLowerCase();
  // A selected pick stays offered whatever the search says: a tile that is not shown cannot be deselected.
  const visible = needle
    ? heroes.filter(
        (hero) => hero.name.toLowerCase().includes(needle) || selected.includes(hero.slug),
      )
    : heroes;

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
    <div className="grid gap-2">
      {heroes.length > SEARCH_THRESHOLD && (
        <Input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label={t("search")}
          placeholder={t("search")}
          size="sm"
        />
      )}
      <div className="flex flex-wrap gap-1.5">
        {visible.map((hero) => {
          const index = selected.indexOf(hero.slug);
          const isSelected = index >= 0;
          // At the cap, unselected heroes stay focusable and announce their state:
          // `disabled` silently removed ~40 controls from the tab order with only
          // a counter to explain it.
          const blocked = !isSelected && atMax;

          return (
            <Button
              key={hero.slug}
              type="button"
              variant="ghost"
              size="icon"
              aria-disabled={blocked}
              aria-pressed={isSelected}
              title={hero.name}
              onClick={(event) => {
                event.stopPropagation();
                toggle(hero.slug);
              }}
              style={isSelected ? accent.selectedCard : undefined}
              className={cn(
                "relative rounded-lg border transition-[opacity,border-color]",
                isSelected
                  ? "border-transparent"
                  : blocked
                    ? "cursor-default border-[color:var(--aqt-border)] opacity-35"
                    : "border-[color:var(--aqt-border-2)] opacity-80 hover:border-[color:var(--aqt-border-3)] hover:opacity-100",
              )}
            >
              <span className="block size-full overflow-hidden rounded-[7px]">
                <CatalogEntityImage entity={hero} size={36} rounded="lg" className="border-0" />
              </span>
              {isSelected && (
                <span className="absolute -right-1 -top-1 flex size-4 items-center justify-center rounded-full bg-[color:var(--aqt-teal)] text-label font-bold leading-none tabular-nums text-[color:var(--aqt-bg)] shadow">
                  {index + 1}
                </span>
              )}
            </Button>
          );
        })}
      </div>
    </div>
  );
}
