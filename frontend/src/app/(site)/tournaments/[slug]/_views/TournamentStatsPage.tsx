"use client";

import { useMemo } from "react";
import Image from "next/image";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ImageOff } from "lucide-react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { TournamentTeamCardFrame } from "@/components/TournamentTeamCard";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { tournamentHref } from "@/lib/tournament/url";
import { cn } from "@/lib/utils";
import heroService from "@/services/hero.service";
import { normalizePlayerRole, playerRoleSlotCode, type PlayerRoleSlotCode } from "@/lib/roster/player-role";
import type { Encounter } from "@/types/encounter.types";
import type { HeroPlaytime } from "@/types/hero.types";
import type { Tournament } from "@/types/tournament.types";

import styles from "../TournamentDetail.module.css";
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

type RoleKey = Exclude<PlayerRoleSlotCode, "flex">;
const ROLE_ORDER: RoleKey[] = ["tank", "damage", "support"];

export const getHeroesQueryPresentation = (state: PublicPageQueryState) =>
  getPublicPageQueryPresentation(state);

const toPercent = (share: number) =>
  Number.isFinite(share) ? Math.min(100, Math.max(0, share * 100)) : 0;

/**
 * A hero's share of all play-time, and its bar against the column's leader.
 * On the absolute 0–100% scale the leader of a 53-hero pool filled a sixth of
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

function heroRole(playtime: HeroPlaytime): RoleKey {
  const slotCode = playerRoleSlotCode(normalizePlayerRole(playtime.hero.type ?? playtime.hero.role));
  return slotCode === "flex" ? "damage" : slotCode;
}

/** `heroes` first: hero play-time is what the section answered before maps joined it. */
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
      if (match.time != null) {
        entry.durationSec += match.time;
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

function HeroesTab({
  tournament,
  tournamentId
}: Readonly<{ tournament: Tournament; tournamentId: number }>) {
  const t = useTranslations();
  const statsQuery = useQuery({
    queryKey: tournamentQueryKeys.heroPlaytime(tournamentId),
    queryFn: () =>
      heroService.getHeroPlaytime(1, -1, "all", tournament.id, {
        workspaceId: tournament.workspace_id
      })
  });
  const heroes = useMemo(
    () =>
      statsQuery.data ? [...statsQuery.data.results].sort((a, b) => b.playtime - a.playtime) : [],
    [statsQuery.data]
  );
  // One ranked column per role: the columns are the filter, so a reader
  // compares the tank pool with itself instead of scrolling past 53 rows.
  const columns = ROLE_ORDER.map((role) => ({
    role,
    heroes: heroes.filter((hero) => heroRole(hero) === role)
  })).filter((column) => column.heroes.length > 0);
  const presentation = getHeroesQueryPresentation({
    data: statsQuery.data,
    itemCount: heroes.length,
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
          {columns.map(({ role, heroes: roleHeroes }) => {
            const roleName = t(`common.roles.${role}`);
            const roleShare = roleHeroes.reduce((sum, hero) => sum + toPercent(hero.playtime), 0);
            return (
              <TournamentTeamCardFrame
                key={role}
                aria-label={roleName}
                name={
                  <span className="inline-flex items-center gap-2">
                    <PlayerRoleIcon role={normalizePlayerRole(role)} size={18} decorative />
                    {roleName}
                    {/* The role's share of all play-time, said beside its name;
                        every value below carries its own % sign. */}
                    <span className="aqt-tnum font-normal text-[color:var(--aqt-fg-dim)]">
                      · {roleShare.toFixed(1)}%
                    </span>
                  </span>
                }
              >
                <ol className="py-1.5">
                  {roleHeroes.map((hero, index) => {
                    const { sharePercent, barWidthPercent } = getHeroPlaytimeMetric(
                      hero.playtime,
                      roleHeroes[0].playtime
                    );
                    const valueText = `${sharePercent.toFixed(1)} ${t("common.playtimeLabel")}`;
                    return (
                      <li
                        key={hero.hero.id}
                        data-rank={index + 1}
                        className="grid grid-cols-[1.25rem_28px_minmax(0,1fr)_3.25rem] items-center gap-x-2.5 px-3.5 py-1.5"
                      >
                        <span
                          aria-hidden="true"
                          className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]"
                        >
                          {String(index + 1).padStart(2, "0")}
                        </span>
                        <Avatar className="size-7 border-none bg-transparent">
                          {hero.hero.image_path ? (
                            <AvatarImage
                              src={hero.hero.image_path}
                              alt=""
                              className="object-contain"
                            />
                          ) : null}
                          <AvatarFallback className="bg-transparent" />
                        </Avatar>
                        <span className="flex min-w-0 flex-col gap-1">
                          <span className="truncate text-caption font-semibold">
                            {hero.hero.name}
                          </span>
                          <span
                            role="progressbar"
                            aria-label={`${hero.hero.name}: ${valueText}`}
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
                                backgroundColor: hero.hero.color || `var(--aqt-${role})`
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
  const mapPool = useTournamentMapPool(tournament.id);
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
              <tr className="border-b border-[color:var(--aqt-overlay-border)] text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
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
                              className="truncate font-semibold after:absolute after:inset-0 hover:text-[color:var(--aqt-teal)] focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-[color:var(--aqt-teal)]"
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
                            {map.gamemode?.image_path ? (
                              <Image
                                src={map.gamemode.image_path}
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
 * Statistics: hero play-time and how often each map was played, as two sub-tabs
 * of one section.
 *
 * The pool itself is not here — it went back to its own `maps` section, which
 * is open before the tournament starts while this one is still locked. What
 * stays is the part that only exists once matches have been played.
 */
const TournamentStatsPage = ({
  tournamentId,
  slug
}: Readonly<{ tournamentId: number; slug: string }>) => {
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
    <section className={styles.publicDataPage} aria-label={t("tournamentDetail.stats.title")}>
      {/* Sub-tabs, not a view density switch: hiding them below `sm` would make
          the map table unreachable on a phone, so `hideOnMobile` stays off. */}
      <div className={styles.controlRail}>
        <ViewSegment
          param="tab"
          options={[
            { value: "heroes", label: t("common.heroes") },
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
        <HeroesTab tournament={tournament} tournamentId={tournamentId} />
      )}
    </section>
  );
};

export default TournamentStatsPage;
