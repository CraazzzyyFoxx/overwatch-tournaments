"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Card } from "@/components/ui/card";
import { FilterChip } from "@/components/ui/filter-chip";
import { useRoleName } from "@/hooks/useRoleName";
import { characterClass } from "@/lib/catalog/attrs";
import { useFormatter } from "@/lib/datetime/client";
import { findRole, ratedDimension } from "@/lib/roster/ontology";
import { tint } from "@/lib/colors";
import type { CatalogEntityRead } from "@/types/catalog.types";
import type { DisciplineMetadata } from "@/types/discipline.types";
import type { CharacterLeaderboardEntry } from "@/types/statistics.types";

import type { RankedEntry } from "./board";
import { COL, type StatKey } from "./stat-columns";

const median = (values: number[]): number | null => {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
};

const Fact = ({ label, value, sub }: Readonly<{ label: string; value: ReactNode; sub?: ReactNode }>) => (
  <div className="flex min-w-0 flex-col gap-1">
    <span className="text-label text-[color:var(--aqt-fg-dim)]">{label}</span>
    <b className="font-onest text-2xl font-bold leading-none tabular-nums text-[color:var(--aqt-fg)]">{value}</b>
    {sub ? <span className="min-w-0 truncate text-label text-[color:var(--aqt-fg-dim)]">{sub}</span> : null}
  </div>
);

/**
 * The board's hero: portrait, class (the game's role glyph when the class is a rated role), the figures over the
 * ranked players, and "Rank by" — the board's columns as one row of chips that re-order the table and the chart.
 */
export default function HeroCard({
  character,
  metadata,
  rows,
  ranked,
  minGames,
  columnKeys,
  sortIndex,
  onSortChange
}: Readonly<{
  character: CatalogEntityRead;
  metadata: DisciplineMetadata;
  /** Every player with logged time on the character. */
  rows: readonly CharacterLeaderboardEntry[];
  /** The players at the sample floor. */
  ranked: readonly RankedEntry[];
  minGames: number;
  columnKeys: StatKey[];
  sortIndex: number;
  onSortChange: (colIndex: number) => void;
}>) {
  const t = useTranslations();
  const format = useFormatter();
  const nameOf = useRoleName();
  const heroClass = characterClass(character);
  const dimension = ratedDimension(metadata)?.code ?? null;
  const role = dimension && heroClass ? findRole(metadata, { dimension, role: heroClass }) : null;
  const heroColor = typeof character.attrs.color === "string" ? character.attrs.color : "var(--aqt-teal)";

  const hours = Math.round(rows.reduce((sum, row) => sum + row.playtime_seconds, 0) / 3600);
  const typicalGames = median(rows.map((row) => row.games_played));
  const bestKd = ranked.length
    ? ranked.reduce((best, item) => (item.entry.kd > best.entry.kd ? item : best)).entry
    : undefined;

  return (
    <Card asChild><section className="relative flex flex-col gap-5 overflow-hidden p-5">
      {/* The character's own catalog colour, as a soft light from the corner: data colour, not a UI accent. */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{ background: `radial-gradient(ellipse at 0% 0%, ${tint(heroColor, 16)}, transparent 55%)` }}
      />
      <div className="relative flex items-center gap-4">
        <CatalogEntityImage entity={character} size={84} rounded="lg" decorative className="rounded-xl" />
        <div className="min-w-0">
          {heroClass ? (
            <Eyebrow tone="muted" className="inline-flex items-center gap-1.5">
              {role && dimension ? (
                <PlayerRoleIcon role={{ dimension, role: role.code }} ontology={metadata} size={14} decorative />
              ) : null}
              {role ? nameOf(role) : heroClass}
            </Eyebrow>
          ) : null}
          <h2 className="mt-1 truncate font-onest text-[2.25rem] font-bold leading-none text-[color:var(--aqt-fg)]">
            {character.name}
          </h2>
        </div>
      </div>

      <div className="relative grid grid-cols-2 gap-x-5 gap-y-4 border-y border-[color:var(--aqt-border)] py-4">
        <Fact
          label={t("users.heroesCompare.hero.playersRanked")}
          value={ranked.length}
          sub={
            minGames > 1
              ? t("users.heroesCompare.hero.rankedOf", { min: minGames, total: rows.length })
              : t("users.heroesCompare.hero.withLoggedTime", { name: character.name })
          }
        />
        <Fact
          label={t("users.heroesCompare.hero.timeOn", { name: character.name })}
          value={t("users.heroesCompare.hero.hours", { hours: format.number(hours) })}
          sub={t("users.heroesCompare.hero.playersTotal", { count: rows.length })}
        />
        <Fact
          label={t("users.heroesCompare.hero.typicalSample")}
          value={typicalGames ?? "—"}
          sub={t("users.heroesCompare.hero.medianGames")}
        />
        <Fact
          label={t("users.heroesCompare.hero.bestKd")}
          value={bestKd ? COL.kd.formatValue(bestKd.kd) : "—"}
          sub={bestKd ? <span title={bestKd.username}>{bestKd.username}</span> : undefined}
        />
      </div>

      <div className="relative flex flex-col gap-2.5">
        <Eyebrow>{t("users.heroesCompare.hero.rankBy")}</Eyebrow>
        <div className="-mx-5 flex gap-1.5 overflow-x-auto px-5 [scrollbar-width:none] md:mx-0 md:flex-wrap md:px-0 [&::-webkit-scrollbar]:hidden">
          {columnKeys.map((key, i) => {
            const active = i === sortIndex;
            return (
              <FilterChip key={`${key}-${i}`} active={active} onClick={() => onSortChange(i)} className="shrink-0">
                {t(COL[key].labelKey)}
              </FilterChip>
            );
          })}
        </div>
      </div>
    </section></Card>
  );
}
