"use client";

import { useTranslations } from "next-intl";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { characterClassOf, classRank } from "@/components/pick-ban/pick-ban-model";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import { useRoleName } from "@/hooks/useRoleName";
import { findRole, ratedDimension } from "@/lib/roster/ontology";
import { cn } from "@/lib/utils";
import type { CatalogEntityRead } from "@/types/catalog.types";
import type { DisciplineMetadata } from "@/types/discipline.types";

/** A roster this long or shorter fits the rail; a longer one (League of Legends) keeps the searchable picker. */
export const RAIL_MAX_CHARACTERS = 60;

/**
 * Every character of the browsed game as a portrait, one row per class in the game's declared order; a class that
 * is a rated role of the game wears that role's glyph and name. One click picks the board's character. On a phone
 * each row scrolls sideways instead of wrapping into a wall of portraits.
 */
export default function HeroRail({
  heroes,
  selectedId,
  ontology,
  onSelect
}: Readonly<{
  heroes: readonly CatalogEntityRead[];
  selectedId: number | undefined;
  /** Class order and role glyphs; until it loads the rows read their bare class codes. */
  ontology: DisciplineMetadata | undefined;
  onSelect: (id: number) => void;
}>) {
  const t = useTranslations();
  const nameOf = useRoleName();

  const byClass = new Map<string | null, CatalogEntityRead[]>();
  for (const hero of heroes) {
    const group = characterClassOf(hero);
    byClass.set(group, [...(byClass.get(group) ?? []), hero]);
  }
  const declared = ontology?.discipline.character_classes ?? [];
  const rows = [...byClass].sort(
    ([left], [right]) => classRank(left, declared) - classRank(right, declared) || (left ?? "").localeCompare(right ?? "")
  );
  const dimension = ontology ? (ratedDimension(ontology)?.code ?? null) : null;

  return (
    <Card asChild className="grid gap-2.5 px-4 py-3.5">
      <section aria-label={t("users.heroesCompare.rail.label")}>
        {rows.map(([group, list]) => {
          const role = ontology && dimension && group ? findRole(ontology, { dimension, role: group }) : null;
          const label = role ? nameOf(role) : (group ?? t("users.heroesCompare.rail.noClass"));
          return (
            <div
              key={group ?? ""}
              role="group"
              aria-label={label}
              className="grid gap-2 md:grid-cols-[8rem_minmax(0,1fr)] md:items-center md:gap-3"
            >
              <Eyebrow tone="muted" className="flex items-center gap-2">
                {role && dimension && group ? (
                  <PlayerRoleIcon role={{ dimension, role: group }} ontology={ontology} size={16} decorative />
                ) : null}
                {label}
                <span className="font-semibold tabular-nums tracking-normal text-[color:var(--aqt-fg-faint)]">{list.length}</span>
              </Eyebrow>
              <div className="-mx-4 flex gap-1.5 overflow-x-auto px-4 [scrollbar-width:none] md:mx-0 md:flex-wrap md:overflow-visible md:px-0 [&::-webkit-scrollbar]:hidden">
                {list.map((hero) => {
                  const selected = hero.id === selectedId;
                  return (
                    <Button
                      key={hero.id}
                      variant="ghost"
                      size="inline"
                      aria-pressed={selected}
                      aria-label={hero.name}
                      title={hero.name}
                      onClick={() => onSelect(hero.id)}
                      className={cn(
                        "shrink-0 rounded-[9px] p-px focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]",
                        selected
                          ? "ring-2 ring-[color:var(--aqt-teal)]"
                          : selectedId !== undefined && "opacity-60 hover:opacity-100"
                      )}
                    >
                      <CatalogEntityImage entity={hero} size={40} rounded="lg" decorative />
                    </Button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </section>
    </Card>
  );
}
