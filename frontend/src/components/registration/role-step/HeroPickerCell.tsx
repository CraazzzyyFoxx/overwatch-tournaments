"use client";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { useState } from "react";
import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { Popover, PopoverContent, PopoverTrigger } from "@craazzzyyfoxx/admin-kit/ui/popover";
import type { RoleAccent } from "@/lib/registration/role-accent";
import { cn } from "@/lib/utils";
import type { CatalogEntityRead } from "@/types/catalog.types";

import { HeroPickerBlock } from "./HeroPickerBlock";

/** Avatars shown on the closed trigger before it falls back to a bare count. */
const PREVIEW_LIMIT = 3;

interface HeroPickerCellProps {
  /** The role's own accent (from its ontology presentation). */
  accent: RoleAccent;
  roleLabel: string;
  /** `false` in a one-role game: the picker's names, heading and hint say "top heroes", never the role. */
  showRole?: boolean;
  /** Characters to offer: the owner game's whole roster. */
  heroes: CatalogEntityRead[];
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
  accent,
  roleLabel,
  showRole = true,
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
    .filter((hero): hero is CatalogEntityRead => hero !== undefined);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          disabled={disabled}
          aria-label={
            showRole
              ? t("registration.roles.matrix.heroesLabel", { role: roleLabel, count: selected.length, max })
              : t("registration.roles.matrix.heroesLabelNoRole", { count: selected.length, max })
          }
          className={cn(
            "w-full justify-start px-2",
            selected.length === 0 && "text-[color:var(--aqt-fg-muted)]",
          )}
        >
          {preview.length > 0 ? (
            <span className="flex shrink-0 items-center gap-1">
              {preview.map((hero) => (
                <span
                  key={hero.slug}
                  className="block size-6 overflow-hidden rounded-md border border-[color:var(--aqt-border-2)]"
                >
                  <CatalogEntityImage entity={hero} size={24} rounded="lg" decorative className="border-0" />
                </span>
              ))}
            </span>
          ) : (
            <Plus className="size-3.5 shrink-0" aria-hidden />
          )}
          <span className="ml-auto shrink-0 tabular-nums text-[color:var(--aqt-fg-muted)]">
            {t("registration.roles.topHeroes.count", { count: selected.length, max })}
          </span>
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        aria-label={
          showRole
            ? t("registration.roles.matrix.heroesPickerLabel", { role: roleLabel })
            : t("registration.roles.matrix.heroesPickerLabelNoRole")
        }
        className="w-[min(22rem,calc(100vw-2rem))] space-y-2 p-3"
      >
        <Eyebrow as="p" tone="muted">
          {showRole ? roleLabel : t("registration.roles.topHeroes.title")}
        </Eyebrow>
        <HeroPickerBlock
          heroes={heroes}
          selected={selected}
          max={max}
          accent={accent}
          onChange={onChange}
        />
        {/* `block`: <output> is inline, so the popover's `space-y-2` rhythm
            would skip it. */}
        <output className="block text-label leading-4 text-[color:var(--aqt-fg-muted)]">
          {atMax
            ? t("registration.roles.matrix.heroesAtMax", { max })
            : t(showRole ? "registration.roles.topHeroes.desc" : "registration.roles.topHeroes.descNoRole", { max })}
        </output>
      </PopoverContent>
    </Popover>
  );
}
