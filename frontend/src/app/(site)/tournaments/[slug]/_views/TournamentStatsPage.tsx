"use client";

import { useMemo } from "react";
import Image from "@/components/ui/image";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ImageOff } from "lucide-react";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { characterClassOf, classRank } from "@/components/pick-ban/pick-ban-model";
import { TournamentTeamCardFrame } from "@/components/TournamentTeamCard";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { tournamentCharacterPlaytimeQueryOptions } from "@/lib/tournament/character-playtime-query";
import { tournamentHref } from "@/lib/tournament/url";
import { cn } from "@/lib/utils";
import type { Encounter } from "@/types/encounter.types";
import type { Tournament } from "@/types/tournament.types";
import type { CharacterPlaytime } from "@/types/user.types";

import { TournamentPageState } from "../_components/TournamentPageState";
import {
  TournamentHeroesSkeleton,
  TournamentMapsSkeleton
} from "../_components/TournamentSkeletons";
import { UpdatingBadge } from "../_components/UpdatingBadge";
import { ViewSegment, readViewParam } from "../_components/ViewSegment";
import { useTournamentQuery } from "@/hooks/useTournamentClientData";
import { useTournamentMapPool } from "../_hooks/useTournamentMapPool";
import { tournamentEncountersQueryOptions } from "@/lib/tournament/encounters-query";
import {
  getPublicPageQueryPresentation,
  type PublicPageQueryState
} from "@/lib/public-page-query-presentation";

export const getHeroesQueryPresentation = (state: PublicPageQueryState) =>
  getPublicPageQueryPresentation(state);

const toPercent = (share: number) =>
  Number.isFinite(share) ? Math.min(100, Math.max(0, share * 100)) : 0;

/**
 * A character's share of all play-time, and its bar against the column's leader.
 * On the absolute 0–100% scale the leader of a 53-character pool filled a sixth of
 * the track and most bars were slivers; the exact share is still printed.
 */
export function getHeroPlaytimeMetric(playtime: number, leaderPlaytime: number) {
  const sharePercent = toPercent(playtime);
  const leaderPercent = toPercent(leaderPlaytime);
  return {
    sharePercent,
    barWidthPercent: leaderPercent > 0 ? Math.min(100, (sharePercent / leaderPercent) * 100) : 0
  };
}

/** `heroes` (the URL value) first: character play-time is what the section answered before maps joined it. */
export const STATS_TABS = ["heroes", "maps"] as const;
export type StatsTab = (typeof STATS_TABS)[number];

export type MapPlayedCount = {
  played: number;
  /** Mean map duration in seconds, or null when no map has a recorded length. */
  avgDurationSec: number | null;
};

/**
 * How often each map was played, and how long it took, from the tournament's
 * own series. No attack/defense split: a `Match` carries a score, a duration
 * and a map, and nothing in the read model says which team attacked.
 */
export function buildMapPlayedCounts(
  encounters: readonly Encounter[]
): Record<number, MapPlayedCount> {
  const totals = new Map<number, { played: number; durationSec: number; timed: number }>();

  for (const encounter of encounters) {
    for (const match of encounter.matches ?? []) {
      const entry = totals.get(match.map_id) ?? { played: 0, durationSec: 0, timed: 0 };
      entry.played += 1;
      if (match.duration_s != null) {
        entry.durationSec += match.duration_s;
        entry.timed += 1;
      }
      totals.set(match.map_id, entry);
    }
  }

  const counts: Record<number, MapPlayedCount> = {};
  for (const [mapId, entry] of totals) {
    counts[mapId] = {
      played: entry.played,
      avgDurationSec: entry.timed > 0 ? entry.durationSec / entry.timed : null
    };
  }
  return counts;
}

function clock(seconds: number) {
  return `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}`;
}

function CharactersTab({ tournament }: Readonly<{ tournament: Tournament }>) {
  const t = useTranslations();
  const statsQuery = useQuery(tournamentCharacterPlaytimeQueryOptions(tournament));
  // The game's declared class order; until it loads, classes sort by name.
  const declared = useDisciplineMetadata(tournament.workspace_id, tournament.discipline).data?.discipline
    .character_classes;
  const characters = useMemo(
    () =>
      statsQuery.data ? [...statsQuery.data.results].sort((a, b) => b.playtime - a.playtime) : [],
    [statsQuery.data]
  );
  // One ranked column per character class: the columns are the filter, so a reader
  // compares one class's pool with itself instead of scrolling past 53 rows.
  const columns = useMemo(() => {
    const byClass = new Map<string | null, CharacterPlaytime[]>();
    for (const row of characters) {
      const group = characterClassOf(row.entity);
      byClass.set(group, [...(byClass.get(group) ?? []), row]);
    }
    return [...byClass].sort(
      ([left], [right]) =>
        classRank(left, declared ?? []) - classRank(right, declared ?? []) ||
        (left ?? "").localeCompare(right ?? "")
    );
  }, [characters, declared]);
  const presentation = getHeroesQueryPresentation({
    data: statsQuery.data,
    itemCount: characters.length,
    isPending: statsQuery.isPending,
    isError: statsQuery.isError,
    isFetching: statsQuery.isFetching
  });

  if (presentation.initialState === "error") {
    return <TournamentPageState state="initial-error" onRetry={() => void statsQuery.refetch()} />;
  }
  if (presentation.initialState === "skeleton" || presentation.contentState === null) {
    return <TournamentHeroesSkeleton />;
  }

  const className = (group: string | null) => {
    // A class code is catalog data; only a code that happens to have a localized word gets one.
    const key = `common.roles.${group}` as "common.roles.tank";
    return group === null ? "—" : t.has(key) ? t(key) : group;
  };

  const content = (
    <>
      {presentation.showUpdating ? <UpdatingBadge /> : null}

      {presentation.contentState === "empty" ? (
        <TournamentPageState
          state="empty"
          title={t("tournamentDetail.stats.heroes.emptyTitle")}
          description={t("tournamentDetail.stats.heroes.emptyDescription")}
        />
      ) : (
        <div className="grid gap-3 lg:grid-cols-3 lg:items-start">
          {columns.map(([group, rows]) => {
            const label = className(group);
            const classShare = rows.reduce((sum, row) => sum + toPercent(row.playtime), 0);
            return (
              <TournamentTeamCardFrame
                key={group ?? ""}
                aria-label={label}
                name={
                  <span className="inline-flex items-center gap-2 capitalize">
                    {label}
                    {/* The class's share of all play-time, said beside its name;
                        every value below carries its own % sign. */}
                    <span className="aqt-tnum font-normal text-[color:var(--aqt-fg-dim)]">
                      · {classShare.toFixed(1)}%
                    </span>
                  </span>
                }
              >
                <ol className="py-1.5">
                  {rows.map((row, index) => {
                    const { sharePercent, barWidthPercent } = getHeroPlaytimeMetric(
                      row.playtime,
                      rows[0].playtime
                    );
                    const valueText = `${sharePercent.toFixed(1)} ${t("common.playtimeLabel")}`;
                    const color = row.entity.attrs.color;
                    return (
                      <li
                        key={row.entity.id}
                        data-rank={index + 1}
                        className="grid grid-cols-[1.25rem_28px_minmax(0,1fr)_3.25rem] items-center gap-x-2.5 px-3.5 py-1.5"
                      >
                        <span
                          aria-hidden="true"
                          className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]"
                        >
                          {String(index + 1).padStart(2, "0")}
                        </span>
                        <CatalogEntityImage entity={row.entity} size={28} decorative />
                        <span className="flex min-w-0 flex-col gap-1">
                          <span className="truncate text-caption font-semibold">
                            {row.entity.name}
                          </span>
                          <span
                            role="progressbar"
                            aria-label={`${row.entity.name}: ${valueText}`}
                            aria-valuemin={0}
                            aria-valuemax={100}
                            aria-valuenow={sharePercent}
                            aria-valuetext={valueText}
                            className="block h-1.5 overflow-hidden rounded-full bg-[color:var(--aqt-overlay-2)]"
                          >
                            <span
                              className="block h-full rounded-full"
                              style={{
                                width: `${barWidthPercent}%`,
                                backgroundColor: typeof color === "string" && color ? color : "var(--aqt-teal)"
                              }}
                            />
                          </span>
                        </span>
                        <span className="aqt-tnum text-right text-caption font-semibold text-[color:var(--aqt-fg)]">
                          {sharePercent.toFixed(1)}%
                        </span>
                      </li>
                    );
                  })}
                </ol>
              </TournamentTeamCardFrame>
            );
          })}
        </div>
      )}
    </>
  );

  if (presentation.showRefreshError) {
    return (
      <TournamentPageState
        state="refresh-error"
        onRetry={() => void statsQuery.refetch()}
        isUpdating={statsQuery.isFetching}
      >
        {content}
      </TournamentPageState>
    );
  }

  return content;
}

/**
 * How often each map of the pool was played, as a table.
 *
 * Every map of the pool is a row, including one nobody picked: the pool is the
 * regulation, so a map missing from it is a different statement from a map that
 * went unplayed, and a table built from match logs alone could not tell them
 * apart. Rows are ordered by plays, because that is the question a statistic
 * answers; the thumbnail is there so the row is recognisable at a glance, the
 * way the Maps section is.
 */
function MapsTab({ tournament, slug }: Readonly<{ tournament: Tournament; slug: string }>) {
  const t = useTranslations();
  const mapPool = useTournamentMapPool(tournament.id, tournament.discipline);
  // The matches section's own all-encounters-with-maps entry, not the bracket's
  // `tournamentQueryKeys.encounters`: the bracket asks for no `matches` entity,
  // so counting map plays out of it would depend on which screen mounted first.
  const playedQuery = useQuery(tournamentEncountersQueryOptions(tournament));

  const playedCounts = useMemo(
    () => buildMapPlayedCounts(playedQuery.data?.results ?? []),
    [playedQuery.data]
  );

  // One presentation for both reads: a pool without its play counts would
  // render every row as "0 played", which is a different statement from "we
  // could not load the matches".
  const poolLoaded = !mapPool.isPending && !(mapPool.isError && mapPool.pool.total === 0);
  const presentation = getPublicPageQueryPresentation({
    data: poolLoaded && playedQuery.data !== undefined ? mapPool.pool : undefined,
    itemCount: mapPool.pool.total,
    isPending: mapPool.isPending || playedQuery.isPending,
    isError: mapPool.isError || playedQuery.isError,
    isFetching: mapPool.isFetching || playedQuery.isFetching
  });
  const retry = () => {
    mapPool.refetch();
    void playedQuery.refetch();
  };

  if (presentation.initialState === "error") {
    return <TournamentPageState state="initial-error" onRetry={() => void retry()} />;
  }
  if (presentation.initialState === "skeleton" || presentation.contentState === null) {
    return <TournamentMapsSkeleton />;
  }

  const rows = mapPool.pool.byGamemode
    .flatMap((group) => group.maps.map((map) => ({ map, mode: group.gamemode })))
    .sort((left, right) => {
      const delta =
        (playedCounts[right.map.id]?.played ?? 0) - (playedCounts[left.map.id]?.played ?? 0);
      return delta !== 0 ? delta : left.map.name.localeCompare(right.map.name);
    });
  // The bars are read against the most-played map, like the hero bars against
  // their leader: the question is "how popular", not "what fraction of 100".
  const mostPlayed = Math.max(1, ...rows.map(({ map }) => playedCounts[map.id]?.played ?? 0));

  const content = (
    <>
      {presentation.showUpdating ? <UpdatingBadge /> : null}

      {presentation.contentState === "empty" ? (
        <TournamentPageState
          state="empty"
          title={t("tournamentDetail.stats.maps.emptyTitle")}
          description={t("tournamentDetail.stats.maps.emptyDescription")}
        />
      ) : (
        <div
          id="map-stats"
          className="scroll-mt-28 overflow-x-auto rounded-[12px] border border-[color:var(--aqt-overlay-border)] bg-[color:var(--aqt-overlay-1)]"
        >
          <table className="w-full text-sm">
            <thead>
              <tr className={cn(eyebrowClass(), "border-b border-[color:var(--aqt-overlay-border)]")}>
                <th scope="col" className="py-2.5 pl-3.5 pr-3 text-left font-medium">
                  {t("tournamentDetail.mapPool.col.map")}
                </th>
                <th scope="col" className="py-2.5 pr-3 text-right font-medium sm:w-[45%] sm:text-left">
                  {t("tournamentDetail.mapPool.col.played")}
                </th>
                <th scope="col" className="py-2.5 pr-3.5 text-right font-medium">
                  {t("tournamentDetail.mapPool.col.avgDuration")}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ map, mode }) => {
                const counts = playedCounts[map.id];
                const played = counts?.played ?? 0;
                const muted = played === 0;
                return (
                  <tr
                    key={map.id}
                    className={cn(
                      "relative border-b border-[color:var(--aqt-overlay-border)] last:border-b-0",
                      muted
                        ? "text-[color:var(--aqt-fg-dim)]"
                        : "transition-colors hover:bg-[color:var(--aqt-overlay-2)]"
                    )}
                  >
                    <td className="py-2 pl-3.5 pr-3">
                      <span className="flex items-center gap-3">
                        <span className="relative hidden aspect-video w-16 shrink-0 overflow-hidden rounded border border-[color:var(--aqt-border)] sm:block">
                          {map.image_path ? (
                            <Image src={map.image_path} alt="" fill sizes="64px" className="object-cover" />
                          ) : (
                            <span className="grid h-full place-items-center text-[color:var(--aqt-fg-faint)]">
                              <ImageOff aria-hidden width={12} height={12} />
                            </span>
                          )}
                        </span>
                        <span className="flex min-w-0 flex-col">
                          {/* A played map is one link for the whole row: its
                              name, stretched over the row. */}
                          {played > 0 ? (
                            <Link
                              data-map-name
                              href={tournamentHref({ slug }, `/matches?map=${map.id}`)}
                              title={t("common.matches")}
                              className="truncate font-semibold after:absolute after:inset-0 hover:text-[color:var(--aqt-teal)] focus-visible:outline-hidden focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-[color:var(--aqt-teal)]"
                            >
                              {map.name}
                            </Link>
                          ) : (
                            <span data-map-name className="truncate">
                              {map.name}
                            </span>
                          )}
                          <span
                            data-map-mode
                            className="flex items-center gap-1.5 text-label text-[color:var(--aqt-fg-muted)]"
                          >
                            {map.parent?.image_path ? (
                              <Image
                                src={map.parent.image_path}
                                alt=""
                                width={12}
                                height={12}
                                aria-hidden
                              />
                            ) : null}
                            {mode}
                          </span>
                        </span>
                      </span>
                    </td>
                    <td className="py-2 pr-3">
                      <span className="flex items-center justify-end gap-3 sm:justify-start">
                        {/* The bar is the glance; under 640px the count alone
                            keeps the row on screen. */}
                        <span
                          aria-hidden
                          className="hidden h-1.5 flex-1 overflow-hidden rounded-full bg-[color:var(--aqt-overlay-2)] sm:block"
                        >
                          <span
                            className="block h-full rounded-full bg-[color:var(--aqt-teal)]"
                            style={{ width: `${(played / mostPlayed) * 100}%` }}
                          />
                        </span>
                        <span className="aqt-tnum w-6 text-right font-semibold">{played}</span>
                      </span>
                    </td>
                    <td className="aqt-tnum py-2 pr-3.5 text-right">
                      {counts?.avgDurationSec != null ? clock(counts.avgDurationSec) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );

  if (presentation.showRefreshError) {
    return (
      <TournamentPageState
        state="refresh-error"
        onRetry={() => void retry()}
        isUpdating={presentation.showUpdating}
      >
        {content}
      </TournamentPageState>
    );
  }

  return content;
}

/**
 * Statistics: character play-time and how often each map was played, as two sub-tabs
 * of one section.
 *
 * The pool itself is not here — it went back to its own `maps` section, which
 * is open before the tournament starts while this one is still locked. What
 * stays is the part that only exists once matches have been played.
 */
const TournamentStatsPage = ({ slug }: Readonly<{ slug: string }>) => {
  const t = useTranslations();
  const searchParams = useSearchParams();
  const tab = readViewParam(searchParams, "tab", STATS_TABS, "heroes");
  // Keyed by `slug`: shares TournamentClientLayout's overview cache entry
  // instead of refetching under a different key.
  const tournamentQuery = useTournamentQuery(slug);
  const tournament = tournamentQuery.data;

  if (!tournament) {
    if (tournamentQuery.isError) {
      return (
        <TournamentPageState state="initial-error" onRetry={() => void tournamentQuery.refetch()} />
      );
    }
    return tab === "maps" ? <TournamentMapsSkeleton /> : <TournamentHeroesSkeleton />;
  }

  return (
    <section className="grid w-full min-w-0 max-w-full gap-4 *:min-w-0" aria-label={t("tournamentDetail.stats.title")}>
      {/* Sub-tabs, not a view density switch: hiding them below `sm` would make
          the map table unreachable on a phone, so `hideOnMobile` stays off. */}
      <div className="flex min-w-0 max-w-full gap-1.75 overflow-x-auto overflow-y-hidden overscroll-x-contain py-0.5 [scrollbar-width:thin] *:flex-none">
        <ViewSegment
          param="tab"
          options={[
            { value: "heroes", label: t("common.characters") },
            { value: "maps", label: t("common.maps") }
          ]}
          defaultValue="heroes"
          label={t("tournamentDetail.stats.tabsLabel")}
          hideOnMobile={false}
        />
      </div>

      {tab === "maps" ? (
        <MapsTab tournament={tournament} slug={slug} />
      ) : (
        <CharactersTab tournament={tournament} />
      )}
    </section>
  );
};

export default TournamentStatsPage;
