"use client";

import { useQueries } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import dynamic from "next/dynamic";
import { useFormatter } from "@/lib/datetime/client";

import { cn } from "@/lib/utils";
import { PageStateCard } from "@/components/ui/page-state-card";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { PerformanceBadge } from "@/components/PerformanceBadge";
import TeamName from "@/components/TeamName";
import { HeroStrip } from "@/components/hero/HeroImage";
import MatchTeamComparison from "@/app/(site)/matches/[id]/components/MatchTeamComparison";
import MatchLeaders from "@/app/(site)/matches/[id]/components/MatchLeaders";
import { Skeleton } from "@/components/ui/skeleton";
import encounterService from "@/services/encounter.service";
import type { MatchWithStats } from "@/types/encounter.types";
import type { PlayerWithStats } from "@/types/team.types";
import type { DivisionGridVersion } from "@/types/workspace.types";
import { LogStatsName } from "@/types/stats.types";
import {
  COLUMN_PRESETS,
  STAT_META,
  formatStat,
  playerStat,
  columnMaxima,
  GROUP_COLOR
} from "@/lib/match-stats";
import { sortTeamPlayers } from "@/lib/player";
import { aggregateSeriesStats, type SeriesAggregate } from "@/lib/encounter/detail";
import { Fact, PlayerIdentity } from "@/components/match/EncounterAtoms";
import styles from "@/components/match/EncounterDetail.module.css";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";

// Same chart, same reason as `MatchStatsSection`: recharts only loads once the
// series stats are on screen. The placeholder holds the chart's minimum height
// so the stats grid does not reflow under it.
const MatchContributionChart = dynamic(
  () => import("@/app/(site)/matches/[id]/components/MatchContributionChart"),
  { ssr: false, loading: () => <Skeleton className="h-70 w-full rounded-lg" /> }
);

interface EncounterSeriesStatsProps {
  matchIds: number[];
  homeTeamId: number;
  awayTeamId: number;
  tournamentGrid?: DivisionGridVersion | null;
}

/**
 * Series-wide statistics: the whole encounter as one scoreboard.
 *
 * Nothing like this existed before — stats were reachable only one map at a
 * time, inside a modal, so "who carried the series" was a question the page
 * could not answer. Each map is fetched under the same `["match-detail", id]`
 * key the per-map dialogs use, so opening a map afterwards costs nothing.
 *
 * The three panels are the existing per-map components fed synthetic
 * whole-series teams (see `aggregateSeriesStats`), rather than a parallel set of
 * charts that could drift from them.
 */
export default function EncounterSeriesStats({
  matchIds,
  homeTeamId,
  awayTeamId,
  tournamentGrid
}: Readonly<EncounterSeriesStatsProps>) {
  const t = useTranslations();

  const queries = useQueries({
    queries: matchIds.map((id) => ({
      queryKey: encounterQueryKeys.matchDetail(id),
      queryFn: () => encounterService.getMatch(id),
      staleTime: 5 * 60_000
    }))
  });

  const loaded = queries
    .map((query) => query.data)
    .filter((data): data is MatchWithStats => data != null);
  const isLoading = queries.some((query) => query.isPending);
  const failedAll = queries.length > 0 && queries.every((query) => query.isError);

  // Folded on every render rather than memoized: `useQueries` hands back a new
  // array each time, so a manual `useMemo` could not be keyed on it without
  // defeating the React Compiler — and the fold is a few thousand additions.
  const aggregate =
    loaded.length > 0
      ? aggregateSeriesStats(loaded, { home_team_id: homeTeamId, away_team_id: awayTeamId })
      : null;

  if (failedAll) {
    return (
      <PageStateCard
        state="error"
        onAction={() => queries.forEach((query) => void query.refetch())}
      />
    );
  }

  if (!aggregate) {
    return isLoading ? <SeriesStatsSkeleton /> : <PageStateCard state="empty" />;
  }

  const partial = loaded.length < matchIds.length;

  return (
    <div className={styles.statsStack}>
      <div className={styles.card}>
        <div className={cn(styles.factGrid, styles.factGridFlush)}>
          <Fact label={t("encounters.detail.statsMapsCounted")}>
            {t("encounters.detail.statsMapsCountedValue", {
              counted: aggregate.mapsCounted,
              total: matchIds.length
            })}
          </Fact>
          <Fact label={t("encounters.detail.statsScope")}>
            {t("encounters.detail.statsScopeValue")}
          </Fact>
          <Fact label={t("encounters.detail.statsRoster")}>
            {aggregate.home.players.length + aggregate.away.players.length}
          </Fact>
        </div>
        {/* `block`: <output> is inline by default, so .cardBody's padding
            would not reserve any vertical space. */}
        {partial ? (
          <output className={cn("block", styles.cardBody, styles.statsNotice)}>
            {t("encounters.detail.statsPartial", {
              counted: loaded.length,
              total: matchIds.length
            })}
          </output>
        ) : null}
      </div>

      <div className={styles.statsGrid}>
        <MatchTeamComparison home={aggregate.home} away={aggregate.away} round={aggregate.round} />
        <MatchContributionChart
          home={aggregate.home}
          away={aggregate.away}
          round={aggregate.round}
        />
      </div>

      <MatchLeaders home={aggregate.home} away={aggregate.away} round={aggregate.round} />

      <SeriesPlayerTable aggregate={aggregate} tournamentGrid={tournamentGrid} />
    </div>
  );
}

/**
 * Per-player series totals. Uses the same `overview` column preset as the
 * per-map tables so a reader moving between the two compares like with like.
 */
function SeriesPlayerTable({
  aggregate,
  tournamentGrid
}: Readonly<{
  aggregate: SeriesAggregate;
  tournamentGrid?: DivisionGridVersion | null;
}>) {
  const t = useTranslations();
  const columns = COLUMN_PRESETS.overview;
  const maxima = columnMaxima(aggregate.home, aggregate.away, aggregate.round, columns);

  return (
    <div className={styles.card}>
      <div className={styles.cardHead}>
        <h3 className={styles.cardTitle}>{t("encounters.detail.seriesTableTitle")}</h3>
        <span className={styles.cardSub}>{t("encounters.detail.seriesTableSub")}</span>
      </div>
      <div
        className={styles.seriesScroll}
        tabIndex={0}
        role="group"
        aria-label={t("encounters.detail.seriesTableTitle")}
      >
        <table className={styles.seriesTable}>
          <thead>
            <tr>
              <th scope="col">{t("encounters.team.colName")}</th>
              <th scope="col">{t("encounters.team.colDivision")}</th>
              <th scope="col">{t("common.heroes")}</th>
              <th scope="col" title={t("encounters.detail.colMapsTitle")}>
                {t("encounters.detail.colMaps")}
              </th>
              <th scope="col">{t("matches.stats.rating")}</th>
              {columns.map((name) => {
                const meta = STAT_META[name];
                return (
                  <th
                    key={name}
                    scope="col"
                    title={t(`matches.stat.${meta.labelKey}` as never)}
                    aria-label={t(`matches.stat.${meta.labelKey}` as never)}
                  >
                    {meta.abbr}
                  </th>
                );
              })}
            </tr>
          </thead>
          {[
            { side: "home" as const, team: aggregate.home },
            { side: "away" as const, team: aggregate.away }
          ].map(({ side, team }) => (
            <tbody key={side} className={side === "home" ? styles.sideHome : styles.sideAway}>
              <tr className={styles.seriesSideHead}>
                <td colSpan={5 + columns.length}>
                  <TeamName team={team} size="xs" />
                </td>
              </tr>
              {sortTeamPlayers(team.players).map((player) => (
                <SeriesPlayerRow
                  key={player.id}
                  player={player}
                  round={aggregate.round}
                  columns={columns}
                  maxima={maxima}
                  mapsPlayed={aggregate.meta[player.id]?.mapsPlayed ?? 0}
                  tournamentGrid={tournamentGrid}
                />
              ))}
            </tbody>
          ))}
        </table>
      </div>
    </div>
  );
}

function SeriesPlayerRow({
  player,
  round,
  columns,
  maxima,
  mapsPlayed,
  tournamentGrid
}: Readonly<{
  player: PlayerWithStats;
  round: number;
  columns: LogStatsName[];
  maxima: Record<string, number>;
  mapsPlayed: number;
  tournamentGrid?: DivisionGridVersion | null;
}>) {
  const heroes = player.heroes?.[round] ?? [];
  const placement = player.stats?.[round]?.[LogStatsName.Performance];

  return (
    <tr>
      <td className={styles.seriesPlayerCell}>
        <span className={styles.seriesPlayer}>
          <PlayerRoleIcon role={player.role} size={16} />
          <PlayerIdentity player={player} />
        </span>
      </td>
      <td>
        <span className={styles.rosterCell}>
          <DivisionIcon
            division={player.division}
            width={26}
            height={26}
            tournamentGrid={tournamentGrid}
          />
        </span>
      </td>
      <td>
        <span className={styles.rosterCell}>
          <HeroStrip heroes={heroes} size="sm" limit={6} />
        </span>
      </td>
      <td>{mapsPlayed > 0 ? mapsPlayed : "—"}</td>
      <td className={styles.seriesRatingCell}>
        <span className={styles.seriesRating}>
          <PerformanceBadge performance={placement ?? null} />
        </span>
      </td>
      {columns.map((name) => (
        <SeriesStatCell
          key={name}
          name={name}
          value={playerStat(player, round, name)}
          max={maxima[name] ?? 0}
        />
      ))}
    </tr>
  );
}

/** Value plus the same 3px magnitude bar the per-map tables draw. */
function SeriesStatCell({ name, value, max }: Readonly<{ name: LogStatsName; value: number; max: number }>) {
  const format = useFormatter();
  const meta = STAT_META[name];
  const showBar = meta?.bar && max > 0;

  return (
    <td>
      <span className="inline-flex flex-col items-end gap-1">
        <span>{formatStat(name, value, format)}</span>
        {showBar ? (
          <span
            aria-hidden
            className="h-[3px] w-10 overflow-hidden rounded-full bg-[color:var(--aqt-overlay-3)]"
          >
            <span
              className="block h-full rounded-full"
              style={{
                width: `${Math.min(100, (value / max) * 100)}%`,
                background: GROUP_COLOR[meta.group]
              }}
            />
          </span>
        ) : null}
      </span>
    </td>
  );
}

function SeriesStatsSkeleton() {
  return (
    <div className={styles.statsStack} aria-busy>
      <span className={cn(styles.skeleton, "h-[68px] w-full")} />
      <div className={styles.statsGrid}>
        <span className={cn(styles.skeleton, "h-[320px] w-full")} />
        <span className={cn(styles.skeleton, "h-[320px] w-full")} />
      </div>
      <span className={cn(styles.skeleton, "h-[120px] w-full")} />
      <span className={cn(styles.skeleton, "h-[420px] w-full")} />
    </div>
  );
}

export type { EncounterSeriesStatsProps };
