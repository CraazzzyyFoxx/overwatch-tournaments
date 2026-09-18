"use client";

import { useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ImageOff } from "lucide-react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { FilterChip } from "@/components/ui/filter-chip";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { tournamentHref } from "@/lib/tournament-url";
import { cn } from "@/lib/utils";
import heroService from "@/services/hero.service";
import { normalizePlayerRole, playerRoleSlotCode, type PlayerRoleSlotCode } from "@/lib/player-role";
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
import { useTournamentQuery } from "../_hooks/useTournamentClientData";
import { useTournamentMapPool } from "../_hooks/useTournamentMapPool";
import { tournamentEncountersQueryOptions } from "./TournamentEncountersPage";
import {
  getPublicPageQueryPresentation,
  type PublicPageQueryState
} from "./publicPageQueryPresentation";

type RoleKey = Exclude<PlayerRoleSlotCode, "flex">;
type RoleFilter = "all" | RoleKey;

const ROLE_ORDER: RoleKey[] = ["tank", "damage", "support"];

export const getHeroesQueryPresentation = (state: PublicPageQueryState) =>
  getPublicPageQueryPresentation(state);

export function getHeroPlaytimeMetric(playtime: number) {
  const sharePercent = Number.isFinite(playtime) ? Math.min(100, Math.max(0, playtime * 100)) : 0;

  return { sharePercent, barWidthPercent: sharePercent };
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
  const [roleFilter, setRoleFilter] = useState<RoleFilter>("all");

  const heroes = useMemo(
    () =>
      statsQuery.data ? [...statsQuery.data.results].sort((a, b) => b.playtime - a.playtime) : [],
    [statsQuery.data]
  );
  const roleCounts = useMemo(() => {
    const counts: Record<RoleKey, number> = { tank: 0, damage: 0, support: 0 };
    for (const hero of heroes) counts[heroRole(hero)] += 1;
    return counts;
  }, [heroes]);
  const visible =
    roleFilter === "all" ? heroes : heroes.filter((hero) => heroRole(hero) === roleFilter);
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

      {heroes.length > 0 ? (
        <div
          className={styles.controlRail}
          role="group"
          aria-label={t("tournamentDetail.stats.heroes.roleLabel")}
        >
          <FilterChip
            active={roleFilter === "all"}
            count={heroes.length}
            onClick={() => setRoleFilter("all")}
          >
            {t("common.all")}
          </FilterChip>
          {ROLE_ORDER.filter((role) => roleCounts[role] > 0).map((role) => (
            <FilterChip
              key={role}
              active={roleFilter === role}
              count={roleCounts[role]}
              onClick={() => setRoleFilter(role)}
            >
              {t(`common.roles.${role}`)}
            </FilterChip>
          ))}
        </div>
      ) : null}

      {presentation.contentState === "empty" ? (
        <TournamentPageState
          state="empty"
          title={t("tournamentDetail.stats.heroes.emptyTitle")}
          description={t("tournamentDetail.stats.heroes.emptyDescription")}
        />
      ) : visible.length === 0 ? (
        <TournamentPageState state="filtered-empty" onReset={() => setRoleFilter("all")} />
      ) : (
        <div className={cn("tn-card", styles.heroList)}>
          <div className="hero-bars">
            {visible.map((hero, index) => {
              const role = heroRole(hero);
              const { sharePercent, barWidthPercent } = getHeroPlaytimeMetric(hero.playtime);
              return (
                <div className="hero-row" key={hero.hero.id} data-rank={index + 1}>
                  <div className="hero-name">
                    <span className={styles.heroRank} aria-hidden="true">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <Avatar className="h-[34px] w-[34px] border-none bg-transparent">
                      {hero.hero.image_path ? (
                        <AvatarImage
                          src={hero.hero.image_path}
                          alt={hero.hero.name}
                          className="object-contain"
                        />
                      ) : null}
                      <AvatarFallback className="bg-transparent" />
                    </Avatar>
                    <div className="stack">
                      <span className="nm">{hero.hero.name}</span>
                      <span className="meta">{t(`common.roles.${role}`)}</span>
                    </div>
                  </div>
                  <div
                    className="hero-bar"
                    role="progressbar"
                    aria-label={`${hero.hero.name}: ${sharePercent.toFixed(1)} ${t("common.playtimeLabel")}`}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={sharePercent}
                    aria-valuetext={`${sharePercent.toFixed(1)} ${t("common.playtimeLabel")}`}
                  >
                    <div
                      className={cn(
                        "fill",
                        styles.heroBarFill,
                        !hero.hero.color && role,
                        barWidthPercent === 0 && styles.zeroHeroBar
                      )}
                      style={{
                        width: `${barWidthPercent}%`,
                        backgroundColor: hero.hero.color || undefined
                      }}
                    />
                  </div>
                  <div className="hero-stats">
                    <span className="val">{sharePercent.toFixed(1)}</span>
                    <span className="pct">{t("common.playtimeLabel")}</span>
                  </div>
                </div>
              );
            })}
          </div>
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
        // No card: the table sits on the page like the match list does (§11),
        // with its own horizontal scroller inside.
        <div
          id="map-stats"
          className="scroll-mt-28 overflow-x-auto border-t border-[color:var(--aqt-border)] pt-3"
        >
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[color:var(--aqt-border)] text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
                <th scope="col" className="py-2 pr-3 text-left font-medium">
                  {t("tournamentDetail.mapPool.col.map")}
                </th>
                <th scope="col" className="py-2 pr-3 text-left font-medium">
                  {t("tournamentDetail.mapPool.col.mode")}
                </th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">
                  {t("tournamentDetail.mapPool.col.played")}
                </th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">
                  {t("tournamentDetail.mapPool.col.avgDuration")}
                </th>
                <th scope="col" className="py-2">
                  <span className="sr-only">{t("common.matches")}</span>
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
                      "border-b border-[color:var(--aqt-border)]/60",
                      muted && "text-[color:var(--aqt-fg-dim)]"
                    )}
                  >
                    <td className="py-2 pr-3">
                      <span className="flex items-center gap-2.5">
                        <span className="relative block aspect-video w-14 shrink-0 overflow-hidden rounded border border-[color:var(--aqt-border)]">
                          {map.image_path ? (
                            <Image src={map.image_path} alt="" fill sizes="56px" className="object-cover" />
                          ) : (
                            <span className="grid h-full place-items-center text-[color:var(--aqt-fg-faint)]">
                              <ImageOff aria-hidden width={12} height={12} />
                            </span>
                          )}
                        </span>
                        <span className={cn("truncate", !muted && "font-semibold")}>{map.name}</span>
                      </span>
                    </td>
                    <td className="py-2 pr-3 text-[color:var(--aqt-fg-muted)]">{mode}</td>
                    <td className="aqt-tnum py-2 pr-3 text-right">{played}</td>
                    <td className="aqt-tnum py-2 pr-3 text-right">
                      {counts?.avgDurationSec != null ? clock(counts.avgDurationSec) : "—"}
                    </td>
                    <td className="py-2 text-right">
                      {played > 0 ? (
                        <Link
                          href={tournamentHref({ slug }, `/matches?map=${map.id}`)}
                          className="text-label text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-teal)]"
                        >
                          {t("common.matches")} →
                        </Link>
                      ) : null}
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
