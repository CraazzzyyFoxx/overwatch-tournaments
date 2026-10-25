"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { LoadErrorNote } from "@/components/kit/EmptyNote";
import { CardSurface } from "@/components/profile/atoms";
import { Skeleton } from "@/components/ui/skeleton";
import { LOW_SAMPLE_GAMES, winrateColor } from "@/lib/colors";
import { cn } from "@/lib/utils";

import type { HeroMapRow } from "./hero-stats";

/**
 * The maps the hero was played on, most played first, with the record and winrate on each (greyed on a low sample).
 * `rows` is `undefined` while the maps load; `onRetry` is set when they failed to.
 */
const MapsForHero = ({
  heroName,
  rows,
  onRetry,
  fill = false,
  className
}: {
  heroName: string;
  rows: HeroMapRow[] | undefined;
  onRetry?: () => void;
  /**
   * Beside another card from `lg`: the card takes the row's height, which that card sets, and the list scrolls in it
   * instead of growing the row (`contain: size`), so the two cards end on one line.
   */
  fill?: boolean;
  className?: string;
}) => {
  const t = useTranslations();
  const title = t("users.heroes.mapsFor", { hero: heroName });

  let body: ReactNode;
  if (onRetry) {
    body = (
      <div className="p-4">
        <LoadErrorNote onRetry={onRetry} />
      </div>
    );
  } else if (rows === undefined) {
    body = (
      <div className="flex flex-col gap-3 px-4 py-3">
        {Array.from({ length: 5 }, (_, i) => (
          <Skeleton key={i} className="h-8 w-full" />
        ))}
      </div>
    );
  } else if (rows.length === 0) {
    body = (
      <p className={cn("py-6 text-center text-caption text-[color:var(--aqt-fg-dim)]", fill && "lg:my-auto")}>
        {t("users.heroes.noMapData")}
      </p>
    );
  } else {
    body = (
      <div
        role="region"
        aria-label={title}
        tabIndex={0}
        className={cn(
          "max-h-[22.5rem] overflow-y-auto focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]",
          fill && "lg:max-h-none lg:min-h-56 lg:flex-1 lg:[contain:size]"
        )}
      >
        <ul className="divide-y divide-[color:var(--aqt-border)]">
          {rows.map((row) => {
            const pct = row.winRate * 100;
            return (
              <li
                key={row.map.id}
                className="grid grid-cols-[auto_minmax(0,1fr)_auto_3rem] items-center gap-3 px-4 py-2"
              >
                <CatalogEntityImage entity={row.map} shape="wide" size={30} decorative />
                <span className="flex min-w-0 flex-col">
                  <span className="truncate text-body font-medium text-[color:var(--aqt-fg)]">{row.map.name}</span>
                  {row.map.parent ? (
                    <span className="truncate text-label text-[color:var(--aqt-fg-dim)]">{row.map.parent.name}</span>
                  ) : null}
                </span>
                <span className="aqt-tnum text-caption text-[color:var(--aqt-fg-muted)]" title={t("users.heroes.wld")}>
                  {row.win}–{row.loss}
                  {row.draw > 0 ? `–${row.draw}` : ""}
                </span>
                <span
                  className="aqt-tnum text-right text-caption font-bold"
                  style={{ color: winrateColor(pct, row.games < LOW_SAMPLE_GAMES) }}
                >
                  {pct.toFixed(0)}%
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    );
  }

  return (
    <CardSurface
      flush
      className={cn(fill && "lg:flex lg:flex-col", className)}
      bodyClassName={fill ? "lg:flex lg:min-h-0 lg:flex-1 lg:flex-col" : undefined}
      title={title}
      subtitle={rows && rows.length > 0 ? t("users.heroes.mapsSubtitle", { count: rows.length }) : undefined}
    >
      {body}
    </CardSurface>
  );
};

export default MapsForHero;
