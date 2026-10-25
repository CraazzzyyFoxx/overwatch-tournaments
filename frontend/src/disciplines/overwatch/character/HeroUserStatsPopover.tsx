"use client";

import { useTranslations } from "next-intl";

import CharacterCard, { CharacterMapStats, signedPoints } from "@/components/profile/CharacterCard";
import { Eyebrow } from "@/components/ui/eyebrow";
import type { SlotProps } from "@/disciplines/types";
import { characterClass } from "@/lib/catalog/attrs";
import { LOW_SAMPLE_GAMES, winrateColor } from "@/lib/colors";
import { useFormatter } from "@/lib/datetime/client";
import { formatSeconds } from "@/lib/format";
import type { CatalogEntityRead } from "@/types/catalog.types";
import type { DisciplineMetadata } from "@/types/discipline.types";
import type { CharacterSummary } from "@/types/user.types";

import { LogStatsName } from "../stat-names";
import { useHeroClass } from "./classes";
import { CLASS_STATS } from "./hero-stats";
import { formatStatValue, getOverall, heroWinrate } from "./utils";

/** The hero's class as a word in its role colour (no glyph: the card names it once). */
function HeroClassLabel({
  entity,
  metadata
}: Readonly<{ entity: Pick<CatalogEntityRead, "attrs">; metadata: DisciplineMetadata }>) {
  const heroClass = useHeroClass(metadata);
  const cls = characterClass(entity);
  if (!cls) return null;
  return (
    <div className="text-label font-bold uppercase tracking-label" style={{ color: heroClass.color(cls) }}>
      {heroClass.label(cls)}
    </div>
  );
}

/** Overwatch's hero card on the Maps tab (the profile's `characterPopover` slot). */
const HeroMapPopover = ({ entity, mapStats, mapCharacters, mapWinRate, metadata }: SlotProps["characterPopover"]) => (
  <CharacterCard entity={entity} subtitle={<HeroClassLabel entity={entity} metadata={metadata} />}>
    <CharacterMapStats stats={mapStats} characters={mapCharacters} mapWinRate={mapWinRate} />
  </CharacterCard>
);

export default HeroMapPopover;

function StatRow({
  label,
  value,
  you,
  average,
  averageText
}: Readonly<{ label: string; value: string; you: number; average: number | null; averageText: string | null }>) {
  const max = average == null ? 0 : Math.max(you, average) * 1.15;
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-3">
      <Eyebrow as="dt" className="truncate">{label}</Eyebrow>
      <dd className="aqt-tnum text-caption font-bold text-[color:var(--aqt-fg)]">
        {value}
        {averageText ? <span className="sr-only">, {averageText}</span> : null}
      </dd>
      {average != null && max > 0 ? (
        <dd aria-hidden className="relative col-span-2 mt-1.5 h-1" title={averageText ?? undefined}>
          <span
            className="absolute inset-y-0 left-0 rounded-full bg-[color:var(--aqt-teal)]"
            style={{ width: `${(you / max) * 100}%` }}
          />
          <span
            className="absolute -top-[3px] h-2.5 w-0.5 rounded-full bg-[color:var(--aqt-fg)]"
            style={{ left: `${(average / max) * 100}%` }}
          />
        </dd>
      ) : null}
    </div>
  );
}

/**
 * Overwatch's hero card on the profile overview: winrate (vs every player on the hero), the class's three per-10
 * figures against the hero's average, and the career-best game. Comparisons hide below `LOW_SAMPLE_GAMES`.
 */
export function HeroStatsPopover({ hero, metadata }: Readonly<{ hero: CharacterSummary; metadata: DisciplineMetadata }>) {
  const t = useTranslations();
  const format = useFormatter();
  const lowSample = hero.games < LOW_SAMPLE_GAMES;
  const winFrac = heroWinrate(hero);
  const vsAvg =
    !lowSample && winFrac != null && hero.win_rate_all != null ? signedPoints(winFrac - hero.win_rate_all) : null;
  const playtime = getOverall(hero, LogStatsName.HeroTimePlayed);
  const meta = [
    hero.games > 0 ? t("users.maps.gamesCount", { count: hero.games }) : null,
    playtime > 0 ? formatSeconds(playtime) : null
  ]
    .filter(Boolean)
    .join(" · ");

  const label = (name: LogStatsName): string => {
    switch (name) {
      case LogStatsName.DamageBlocked:
        return t("users.heroes.quick.blocked10");
      case LogStatsName.HealingDealt:
        return t("users.heroes.quick.heal10");
      case LogStatsName.FinalBlows:
        return t("users.heroes.quick.finalBlows10");
      case LogStatsName.KDA:
        return t("users.heroes.quick.kda");
      default:
        return t("users.heroes.quick.dmg10");
    }
  };
  const rows = (CLASS_STATS[characterClass(hero.character) ?? ""] ?? CLASS_STATS.damage).flatMap((name) => {
    const stat = hero.stats.find((s) => s.name === name);
    if (!stat || !Number.isFinite(stat.avg_10)) return [];
    const average = !lowSample && stat.avg_10_all > 0 ? stat.avg_10_all : null;
    return [
      {
        name,
        label: label(name),
        value: formatStatValue(format, name, stat.avg_10),
        you: stat.avg_10,
        average,
        averageText:
          average == null ? null : t("users.heroes.card.avg", { value: formatStatValue(format, name, average) })
      }
    ];
  });
  const record = hero.record;

  return (
    <CharacterCard
      entity={hero.character}
      subtitle={<HeroClassLabel entity={hero.character} metadata={metadata} />}
      meta={meta || undefined}
      aside={
        winFrac == null ? null : (
          <div className="shrink-0 text-right">
            <div
              className="aqt-display aqt-tnum text-title font-bold"
              style={{ color: winrateColor(winFrac * 100, lowSample) }}
            >
              <span className="sr-only">{t("common.heroStats.winrate")} </span>
              {(winFrac * 100).toFixed(0)}%
            </div>
            {vsAvg ? (
              <div className="aqt-tnum text-label font-bold" style={{ color: vsAvg.color }}>
                {t("users.heroes.card.vsAvg", { value: vsAvg.text })}
              </div>
            ) : null}
          </div>
        )
      }
    >
      {rows.length > 0 ? (
        <dl className="flex flex-col gap-2.5 border-t border-[color:var(--aqt-border)] pt-3">
          {rows.map((row) => (
            <StatRow key={row.name} {...row} />
          ))}
        </dl>
      ) : null}

      {record ? (
        <dl className="border-t border-[color:var(--aqt-border)] pt-3">
          <Eyebrow as="dt">{t("users.heroes.card.bestGame")}</Eyebrow>
          <dd className="mt-0.5 truncate text-caption font-bold text-[color:var(--aqt-fg)]">
            {t("users.heroes.card.recordValue", {
              stat: record.stat,
              value: formatStatValue(format, record.stat, record.value)
            })}{" "}
            · {record.map_name}
          </dd>
          <dd className="truncate text-caption text-[color:var(--aqt-fg-dim)]" title={record.tournament_name}>
            {record.tournament_name}
          </dd>
        </dl>
      ) : null}

      {rows.length === 0 && !record && winFrac == null ? (
        <p className="text-caption text-[color:var(--aqt-fg-faint)]">{t("users.heroes.noStats")}</p>
      ) : null}
    </CharacterCard>
  );
}
