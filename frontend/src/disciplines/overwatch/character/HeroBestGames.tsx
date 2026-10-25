"use client";

import { Crown } from "lucide-react";
import { useTranslations } from "next-intl";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { CardSurface } from "@/components/profile/atoms";
import { useFormatter } from "@/lib/datetime/client";

import type { StatRow } from "./hero-stats";
import { formatStatValue } from "./utils";

/**
 * The hero's single-game records: each row its map, the value, the stat, and the map and tournament it was set in,
 * linking to the match. A crown marks a record that is also the best of every player on the hero.
 */
const HeroBestGames = ({ rows }: { rows: StatRow[] }) => {
  const t = useTranslations();
  const format = useFormatter();

  return (
    <CardSurface flush title={t("users.heroes.records")}>
      <ul className="divide-y divide-[color:var(--aqt-border)]">
        {rows.flatMap((row) => {
          const best = row.best;
          if (!best) return [];
          const where = `${best.map_name} · ${best.tournament_name}`;
          return [
            <li key={row.name}>
              <HoverPrefetchLink
                href={`/encounters/${best.encounter_id}`}
                className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-4 py-2.5 transition-colors hover:bg-[color:var(--aqt-overlay-2)] focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
              >
                <CatalogEntityImage
                  entity={{ name: best.map_name, image_path: best.map_image_path || null }}
                  shape="wide"
                  size={36}
                  decorative
                />
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="flex min-w-0 items-baseline gap-2">
                    <span className="aqt-display aqt-tnum text-heading font-bold leading-none text-[color:var(--aqt-fg)]">
                      {formatStatValue(format, row.name, best.value)}
                    </span>
                    <span className="truncate text-caption text-[color:var(--aqt-fg-muted)]">
                      {t(row.labelKey as Parameters<typeof t>[0])}
                    </span>
                  </span>
                  <span className="truncate text-label text-[color:var(--aqt-fg-dim)]" title={where}>
                    {where}
                  </span>
                </span>
                {row.holdsRecord ? (
                  <Crown
                    role="img"
                    aria-label={t("users.heroes.allTimeBest")}
                    className="size-4 text-[color:var(--aqt-amber)]"
                  />
                ) : null}
              </HoverPrefetchLink>
            </li>
          ];
        })}
      </ul>
    </CardSurface>
  );
};

export default HeroBestGames;
