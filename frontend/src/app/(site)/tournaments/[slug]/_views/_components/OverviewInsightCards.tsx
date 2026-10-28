"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { ResTag } from "@/components/match/cells";
import PlayerName from "@/components/PlayerName";
import TeamName from "@/components/TeamName";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Separator } from "@/components/ui/separator";
import { useCatalogEntities } from "@/hooks/useCatalogEntities";
import type { CatalogEntityRead } from "@/types/catalog.types";
import type { Encounter } from "@/types/encounter.types";

import {
  oneTricks,
  rankLabel,
  type TeamSeries,
  type TournamentBans
} from "../tournamentInsights.model";
import type { TournamentRoster } from "../useTournamentRoster";
import { OverviewSection, SectionLink } from "./OverviewCards";

/** The tournament game's heroes by catalogue id. */
export function useHeroCatalog(discipline: string) {
  const query = useCatalogEntities(discipline, "character");
  return useMemo(() => new Map((query.data ?? []).map((hero) => [hero.id, hero])), [query.data]);
}

/** A series of the viewer's team as one link row: result square, round, opponent, score. */
export function TeamSeriesRow({
  encounter,
  seat,
  round
}: Readonly<{ encounter: Encounter; seat: TeamSeries; round: string }>) {
  const t = useTranslations("tournamentDetail");
  return (
    <HoverPrefetchLink
      href={`/encounters/${encounter.id}`}
      className="grid grid-cols-[auto_minmax(0,4.5rem)_minmax(0,1fr)_auto] items-center gap-3 rounded-md px-2 py-2 transition-colors hover:bg-[color:var(--aqt-overlay-2)] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--aqt-teal)] sm:grid-cols-[auto_minmax(0,7.5rem)_minmax(0,1fr)_auto]"
    >
      <ResTag kind={seat.result} aria-label={t(`result.word.${seat.result}`)}>
        {t(`result.letter.${seat.result}`)}
      </ResTag>
      <span className="truncate text-label text-[color:var(--aqt-fg-dim)]">{round}</span>
      <TeamName
        team={{ name: seat.theirs.name, image_url: seat.theirs.team?.image_url }}
        size="xs"
        className="text-caption"
      />
      <span className="aqt-tnum text-caption text-[color:var(--aqt-fg-muted)]">
        <span className="font-semibold text-[color:var(--aqt-fg)]">{seat.mine.score}</span>
        {" – "}
        {seat.theirs.score}
      </span>
    </HoverPrefetchLink>
  );
}

/** The most banned heroes and the main one-trick, in the reference column's ranked-list shape. */
export function BansCard({
  bans,
  heroes,
  roster,
  overviewHref,
  title,
  limit = 5
}: Readonly<{
  bans: TournamentBans;
  heroes: Map<number, CatalogEntityRead>;
  roster: TournamentRoster;
  overviewHref: string;
  title?: string;
  /** Rows shown; a page passes more when its side column would otherwise end short. */
  limit?: number;
}>) {
  const t = useTranslations("tournamentDetail");
  const top = bans.heroes.slice(0, limit);
  const leader = top[0]?.bans ?? 1;
  const oneTrick = oneTricks(bans)[0];
  const oneTrickEntry = oneTrick ? roster.byPlayer.get(oneTrick.playerId) : undefined;
  const oneTrickHero = oneTrick ? (heroes.get(oneTrick.heroId) ?? null) : null;

  return (
    <OverviewSection
      title={title ?? t("overview.bans.title")}
      action={<SectionLink href={`${overviewHref}/stats?tab=bans`}>{t("common.more")}</SectionLink>}
    >
      <ol className="grid gap-1.5">
        {top.map((row, index) => {
          const hero = heroes.get(row.id) ?? null;
          return (
            <li
              key={row.id}
              className="grid grid-cols-[1rem_1.5rem_minmax(0,1fr)_auto_2.75rem] items-center gap-2"
            >
              <span aria-hidden className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]">
                {rankLabel(index)}
              </span>
              <CatalogEntityImage entity={hero} size={24} decorative />
              <span className="min-w-0 truncate text-caption">{hero?.name ?? `#${row.id}`}</span>
              <span
                aria-hidden
                className="hidden h-1.5 w-16 overflow-hidden rounded-sm bg-[color:var(--aqt-border)] sm:block"
              >
                <span
                  className="block h-full bg-[color:var(--aqt-fg-muted)]"
                  style={{ width: `${(row.bans / leader) * 100}%` }}
                />
              </span>
              <span className="aqt-tnum text-right text-label text-[color:var(--aqt-fg-muted)]">
                {row.bans}
              </span>
            </li>
          );
        })}
      </ol>
      {oneTrick && oneTrickEntry ? (
        <>
          <Separator className="my-4" />
          <Eyebrow className="block">{t("overview.bans.oneTrick")}</Eyebrow>
          <div className="mt-2 flex items-center gap-3">
            <CatalogEntityImage entity={oneTrickHero} size={32} decorative />
            <span className="min-w-0">
              <PlayerName player={oneTrickEntry.player} className="text-caption" />
              <span className="block truncate text-label text-[color:var(--aqt-fg-dim)]">
                {t("overview.bans.oneTrickLine", {
                  hero: oneTrickHero?.name ?? "—",
                  count: oneTrick.heroBans,
                  total: oneTrick.bans
                })}
              </span>
            </span>
          </div>
        </>
      ) : null}
    </OverviewSection>
  );
}
