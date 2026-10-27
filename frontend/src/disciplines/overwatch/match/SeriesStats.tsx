"use client";

import { useTranslations } from "next-intl";
import dynamic from "next/dynamic";

import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import PlayerName from "@/components/PlayerName";
import { PerformanceBadge } from "@/components/PerformanceBadge";
import TeamName from "@/components/TeamName";
import { CatalogEntityStrip } from "@/components/catalog/CatalogEntityImage";
import { CARD_SUB, CardHead } from "@/components/match/EncounterAtoms";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { SlotProps } from "@/disciplines/types";
import { LogStatsName } from "../stat-names";
import {
  COLUMN_PRESETS,
  STAT_META,
  formatStat,
  playerStat,
  columnMaxima,
  GROUP_COLOR,
  type MatchStatsPlayer
} from "./stats";
import { aggregateSeriesStats, type SeriesAggregate } from "./series";
import TeamComparison from "./TeamComparison";
import Leaders from "./Leaders";

// Same chart, same reason as `MatchStats`: recharts only loads once the
// series stats are on screen. The placeholder holds the chart's minimum height
// so the stats grid does not reflow under it.
const ContributionChart = dynamic(() => import("./ContributionChart"), {
  ssr: false,
  loading: () => <Skeleton className="h-70 w-full rounded-lg" />
});

/** Figures read right-aligned on one line. */
const CELL = "whitespace-nowrap px-2.5 py-2 text-right";
/** The name column stays put while the figures scroll under it. */
const STICKY = "sticky left-0 z-1 text-left";

/**
 * The Overwatch series statistics of an encounter's duel maps: side comparison and leaders (`overview`), or the
 * per-player totals grouped by participation (`players`). The host renders it only when every loaded match is a
 * duel.
 */
export default function SeriesStats({ matches, view }: Readonly<SlotProps["seriesStats"]>) {
  // Folded on every render rather than memoized: the fold is a few thousand additions, and a manual `useMemo`
  // keyed on the host's per-render array would defeat the React Compiler.
  const aggregate = aggregateSeriesStats(matches);
  if (!aggregate) return null;

  const [home, away] = aggregate.participations;
  const isDuel = aggregate.participations.length === 2;

  return view === "overview" && isDuel ? (
    <div className="grid grid-cols-1 items-start gap-3.5 xl:grid-cols-2">
      <TeamComparison home={home} away={away} round={aggregate.round} />
      <Leaders
        home={home}
        away={away}
        round={aggregate.round}
        gridClassName="sm:grid-cols-3 xl:grid-cols-2"
      />
    </div>
  ) : (
    <>
      <SeriesPlayerTable aggregate={aggregate} />
      {isDuel ? <ContributionChart home={home} away={away} round={aggregate.round} /> : null}
    </>
  );
}

/**
 * Per-player series totals. Uses the same `overview` column preset as the
 * per-map tables so a reader moving between the two compares like with like.
 */
function SeriesPlayerTable({
  aggregate
}: Readonly<{
  aggregate: SeriesAggregate;
}>) {
  const t = useTranslations();
  const columns = COLUMN_PRESETS.overview;
  const maxima = columnMaxima(
    { players: aggregate.participations.flatMap((participation) => participation.players) },
    null,
    aggregate.round,
    columns
  );
  const head = "h-auto whitespace-nowrap px-2.5 py-2.25 text-right";

  return (
    <Card className="overflow-hidden">
      <CardHead title={t("encounters.detail.seriesTableTitle")}>
        <span className={CARD_SUB}>{t("encounters.detail.seriesTableSub")}</span>
      </CardHead>
      {/* The labelled scroll region (DESIGN §12) is this div: `Table`'s own
          wrapper takes no label, so it is left unclipped inside it. */}
      <div
        className="overflow-x-auto overscroll-x-contain [scrollbar-width:thin] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        tabIndex={0}
        role="group"
        aria-label={t("encounters.detail.seriesTableTitle")}
      >
        <Table
          wrapperClassName="overflow-visible"
          className="aqt-tnum min-w-[52rem] border-collapse text-[color:var(--aqt-fg-muted)]"
        >
          <TableHeader>
            <TableRow className="bg-[color:var(--aqt-overlay-1)]">
              <TableHead scope="col" className={cn(head, STICKY, "bg-card")}>
                {t("encounters.team.colName")}
              </TableHead>
              <TableHead scope="col" className={head}>
                {t("common.heroes")}
              </TableHead>
              <TableHead scope="col" className={head} title={t("encounters.detail.colMapsTitle")}>
                {t("encounters.detail.colMaps")}
              </TableHead>
              <TableHead scope="col" className={head}>
                {t("matches.stats.rating")}
              </TableHead>
              {columns.map((name) => {
                const meta = STAT_META[name];
                return (
                  <TableHead
                    key={name}
                    scope="col"
                    className={head}
                    title={t(meta.labelKey as never)}
                    aria-label={t(meta.labelKey as never)}
                  >
                    {meta.abbr}
                  </TableHead>
                );
              })}
            </TableRow>
          </TableHeader>
          {aggregate.participations.map((participation) => (
            <TableBody key={participation.id}>
              <TableRow className="hover:bg-transparent">
                <TableCell
                  colSpan={4 + columns.length}
                  className="bg-[color:var(--aqt-overlay-3)] px-2.5 py-2 font-display text-label font-bold text-[color:var(--aqt-fg-dim)]"
                >
                  <TeamName
                    team={{ name: participation.name, image_url: participation.team?.image_url }}
                    size="xs"
                  />
                  <span className={CARD_SUB}>
                    {" · "}
                    {t("encounters.history.participation", { id: participation.id })}
                    {participation.live === false
                      ? ` · ${t("encounters.history.retiredParticipation")}`
                      : null}
                  </span>
                </TableCell>
              </TableRow>
              {participation.players.map((player) => (
                <SeriesPlayerRow
                  key={player.workspace_member_id}
                  player={player}
                  round={aggregate.round}
                  columns={columns}
                  maxima={maxima}
                  mapsPlayed={participation.meta[player.workspace_member_id]?.mapsPlayed ?? 0}
                />
              ))}
            </TableBody>
          ))}
        </Table>
      </div>
    </Card>
  );
}

function SeriesPlayerRow({
  player,
  round,
  columns,
  maxima,
  mapsPlayed
}: Readonly<{
  player: MatchStatsPlayer;
  round: number;
  columns: LogStatsName[];
  maxima: Record<string, number>;
  mapsPlayed: number;
}>) {
  const heroes = player.heroes?.[round] ?? [];
  const placement = player.stats?.[round]?.[LogStatsName.Performance];

  return (
    <TableRow className="group">
      {/* Opaque, so the figures scroll under it; the row hover is layered on top. */}
      <TableCell
        className={cn(
          CELL,
          STICKY,
          "min-w-56 bg-card group-hover:bg-[image:linear-gradient(var(--aqt-overlay-2),var(--aqt-overlay-2))]"
        )}
      >
        <PlayerName
          player={player}
          profileName={player.profile_name}
          includeSpecialization={false}
        />
      </TableCell>
      <TableCell className={CELL}>
        <span className="flex items-center justify-center">
          <CatalogEntityStrip entities={heroes} size="sm" limit={6} />
        </span>
      </TableCell>
      <TableCell className={CELL}>{mapsPlayed > 0 ? mapsPlayed : "—"}</TableCell>
      <TableCell className={cn(CELL, "font-semibold text-[color:var(--aqt-teal)]")}>
        <span className="inline-flex items-center justify-end gap-1.5">
          <PerformanceBadge performance={placement ?? null} />
        </span>
      </TableCell>
      {columns.map((name) => (
        <SeriesStatCell
          key={name}
          name={name}
          value={playerStat(player, round, name)}
          max={maxima[name] ?? 0}
        />
      ))}
    </TableRow>
  );
}

/** Value plus the same 3px magnitude bar the per-map tables draw. */
function SeriesStatCell({
  name,
  value,
  max
}: Readonly<{ name: LogStatsName; value: number; max: number }>) {
  const format = useFormatter();
  const meta = STAT_META[name];
  const showBar = meta?.bar && max > 0;

  return (
    <TableCell className={CELL}>
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
    </TableCell>
  );
}
