"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { LOW_SAMPLE_GAMES, winrateColor } from "@/lib/colors";
import { formatSeconds } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { CatalogEntityRead } from "@/types/catalog.types";
import type { UserMapCharacterStats } from "@/types/user.types";

// ponytail: a fixed share, not a measured width. At the card's 288px a 9% segment is ~26px, room for an 18px portrait;
// measure the segment if the card width changes.
const PORTRAIT_MIN_SHARE = 0.09;

/**
 * A character's hover card on a profile: portrait, name, the game module's `subtitle` (its class) and `meta` line, an
 * optional `aside` figure, then the caller's sections — each opens with its own hairline. Only figures that exist
 * are drawn (DESIGN.md §11).
 */
export default function CharacterCard({
  entity,
  subtitle,
  meta,
  aside,
  children
}: Readonly<{
  entity: Pick<CatalogEntityRead, "name" | "image_path">;
  subtitle?: ReactNode;
  meta?: string;
  aside?: ReactNode;
  children?: ReactNode;
}>) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <CatalogEntityImage entity={entity} size={56} rounded="lg" className="rounded-lg" decorative />
        <div className="min-w-0 flex-1">
          <div className="aqt-display truncate text-heading font-bold text-[color:var(--aqt-fg)]">{entity.name}</div>
          {subtitle}
          {meta ? <div className="aqt-tnum truncate text-caption text-[color:var(--aqt-fg-dim)]">{meta}</div> : null}
        </div>
        {aside}
      </div>
      {children}
    </div>
  );
}

/** A label-over-value fact (DESIGN.md §4: a `<dl>` fact, never a tile). */
function CardFact({ label, value, color }: Readonly<{ label: string; value: string; color?: string }>) {
  return (
    <div className="min-w-0">
      <Eyebrow as="dt" className="truncate">{label}</Eyebrow>
      <dd className="aqt-tnum text-ui font-bold" style={{ color: color ?? "var(--aqt-fg)" }}>
        {value}
      </dd>
    </div>
  );
}

/** A signed percentage-point difference, coloured by direction. */
export const signedPoints = (fraction: number) => {
  const points = Math.round(fraction * 100);
  return {
    text: `${points > 0 ? "+" : points < 0 ? "−" : ""}${Math.abs(points)}%`,
    color: points > 0 ? "var(--aqt-emerald)" : points < 0 ? "var(--aqt-rose)" : "var(--aqt-fg-muted)"
  };
};

/**
 * The map-scoped part of the card (the Maps tab): the character's winrate and record on the map, how it compares to
 * the player's own winrate there, and its slice of the player's time on the map among every character played on it.
 */
export function CharacterMapStats({
  stats,
  characters,
  mapWinRate
}: Readonly<{
  stats: UserMapCharacterStats;
  /** Every character the player played on this map, this one included. */
  characters: UserMapCharacterStats[];
  /** The player's winrate (0..1) on the whole map. */
  mapWinRate: number;
}>) {
  const t = useTranslations("common.heroStats");
  const lowSample = stats.games < LOW_SAMPLE_GAMES;
  const winPct = stats.win_rate * 100;
  const vsMap = lowSample ? null : signedPoints(stats.win_rate - mapWinRate);
  const split = [...characters].sort((a, b) => b.playtime_share_on_map - a.playtime_share_on_map);
  // The maps read returns a map's top five characters only; the rest of its time is one unnamed segment.
  const rest = 1 - split.reduce((sum, row) => sum + row.playtime_share_on_map, 0);

  return (
    <>
      <dl className="grid grid-cols-3 gap-3 border-t border-[color:var(--aqt-border)] pt-3">
        <CardFact label={t("winrate")} value={`${winPct.toFixed(0)}%`} color={winrateColor(winPct, lowSample)} />
        <CardFact label={t("record")} value={`${stats.win}-${stats.loss}-${stats.draw}`} />
        {vsMap ? <CardFact label={t("vsMap")} value={vsMap.text} color={vsMap.color} /> : null}
      </dl>

      <div className="border-t border-[color:var(--aqt-border)] pt-3">
        <div className="flex items-baseline justify-between gap-3">
          <Eyebrow className="truncate">{t("playtimeOnMap")}</Eyebrow>
          <span className="aqt-tnum shrink-0 text-caption font-bold text-[color:var(--aqt-fg)]">
            {formatSeconds(stats.playtime_seconds)} · {(stats.playtime_share_on_map * 100).toFixed(0)}%
          </span>
        </div>
        {/* The figure above says this character's share; the split only places it among the others. */}
        <div aria-hidden className="mt-2 flex gap-0.5">
          {split.map((row) => {
            const current = row.character.id === stats.character.id;
            return (
              <div
                key={row.character.id}
                className="flex min-w-0 flex-col items-center gap-1.5"
                style={{ flexGrow: row.playtime_share_on_map, flexBasis: 0 }}
                title={`${row.character.name} · ${(row.playtime_share_on_map * 100).toFixed(0)}%`}
              >
                <span
                  className={cn(
                    "h-1.5 w-full rounded-full",
                    current ? "bg-[color:var(--aqt-teal)]" : "bg-[color:var(--aqt-border-3)]"
                  )}
                />
                {row.playtime_share_on_map >= PORTRAIT_MIN_SHARE ? (
                  <CatalogEntityImage
                    entity={row.character}
                    size={18}
                    decorative
                    className={current ? "border-[color:var(--aqt-teal)]" : "opacity-70"}
                  />
                ) : null}
              </div>
            );
          })}
          {rest > 0.005 ? (
            <div style={{ flexGrow: rest, flexBasis: 0 }}>
              <span className="block h-1.5 w-full rounded-full bg-[color:var(--aqt-overlay-3)]" />
            </div>
          ) : null}
        </div>
      </div>

      <p className="text-label text-[color:var(--aqt-fg-faint)]">{t("countedNote")}</p>
    </>
  );
}
