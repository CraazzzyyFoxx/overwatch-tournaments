"use client";

import { useMemo, useState } from "react";
import { EyeOff, RotateCcw, Sword } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { SearchField } from "@/components/ui/search-field";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { DivisionGrid, DivisionGridVersion } from "@/types/workspace.types";

import type { RankedEntry } from "./board";
import LeaderboardRow, { CELL, STICKY_PLAYER, STICKY_RANK, type StatCellSpec } from "./LeaderboardRow";
import { ALL_STAT_OPTIONS, COL, type StatKey } from "./stat-columns";
import StatColumnHeader from "./StatColumnHeader";

const SKELETON_ROWS = 15;
const TITLE_ID = "hero-leaderboard-title";

const HEAD_CELL = "border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] px-3 py-2.5 align-middle";
/** The legend's swatches: the heat map's three tinted tiers, palest first. */
const LEGEND = [
  { label: "50%", swatch: "bg-[color:color-mix(in_srgb,var(--aqt-teal)_8%,transparent)]" },
  { label: "75%", swatch: "bg-[color:color-mix(in_srgb,var(--aqt-teal)_17%,transparent)]" },
  { label: "90%", swatch: "bg-[color:color-mix(in_srgb,var(--aqt-teal)_30%,transparent)]" }
];

interface HeroLeaderboardTableProps {
  discipline: string;
  tournamentId: number | undefined;
  /** Every player at the sample floor, ranked: the heat map's scale. */
  ranked: readonly RankedEntry[];
  /** The rows on screen: the search's matches, cut to what the reader asked to see. */
  rows: readonly RankedEntry[];
  /** How many rows the search matches in all. */
  matchCount: number;
  /** Players under the sample floor, left off the board. */
  hiddenCount: number;
  minGames: number;
  /** The grids the rows' divisions are numbers on (`division_grid_version_id`). */
  grids: readonly DivisionGridVersion[];
  /** The read's own grid, for a row naming no version (the workspace's; the game's native ladder across workspaces). */
  divisionGrid: DivisionGrid;
  query: string;
  onQueryChange: (value: string) => void;
  isLoading: boolean;
  columnKeys: StatKey[];
  /** Index into `columnKeys` of the column that drives the shared row order. */
  sortIndex: number;
  sortDir: "asc" | "desc";
  /** Rows the next "show more" adds; 0 when every match is on screen. */
  moreCount: number;
  onColumnSelect: (colIndex: number, key: StatKey) => void;
  onSortChange: (colIndex: number) => void;
  onResetColumns: () => void;
  onShowMore: () => void;
  onShowHidden: () => void;
}

const HeroLeaderboardTable = ({
  discipline,
  tournamentId,
  ranked,
  rows,
  matchCount,
  hiddenCount,
  minGames,
  grids,
  divisionGrid,
  query,
  onQueryChange,
  isLoading,
  columnKeys,
  sortIndex,
  sortDir,
  moreCount,
  onColumnSelect,
  onSortChange,
  onResetColumns,
  onShowMore,
  onShowHidden,
}: HeroLeaderboardTableProps) => {
  const t = useTranslations();
  const [hoveredUserId, setHoveredUserId] = useState<number | null>(null);

  // One scale per column over every ranked player (not the rows on screen), so a tint means the same thing
  // whatever the search or the "show more" cut leaves visible.
  const cells = useMemo<StatCellSpec[]>(
    () =>
      columnKeys.map((key) => {
        const def = COL[key];
        return { def, sorted: ranked.map(({ entry }) => def.getValue(entry)).sort((a, b) => a - b) };
      }),
    [columnKeys, ranked]
  );
  const gridById = useMemo(() => new Map(grids.map((grid) => [grid.id, grid])), [grids]);

  const emptyMessage = query
    ? t("users.heroesCompare.table.noMatches", { query: query.trim() })
    : hiddenCount > 0
      ? t("users.heroesCompare.table.allBelowFloor", { min: minGames })
      : tournamentId
        ? t("users.heroesCompare.table.noDataInTournament")
        : t("users.heroesCompare.table.noData");

  return (
    <Card asChild><section aria-labelledby={TITLE_ID} className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-[color:var(--aqt-border)] px-4 py-3">
        <h2 id={TITLE_ID} className="font-onest text-lg font-semibold text-[color:var(--aqt-fg)]">
          {t("users.heroesCompare.table.allPlayers")}
        </h2>
        {!isLoading ? (
          <span className="rounded-full border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] px-2.5 py-0.5 text-label tabular-nums text-[color:var(--aqt-fg-muted)]">
            {t("users.heroesCompare.table.rankedCount", { count: ranked.length })}
          </span>
        ) : null}
        <span className="flex items-center gap-1.5 text-label text-[color:var(--aqt-fg-faint)] max-md:hidden">
          {t("users.heroesCompare.table.legendLead")}
          {LEGEND.map((item) => (
            <span key={item.label} className="inline-flex items-center gap-1">
              <span aria-hidden className={cn("h-2.5 w-3.5 rounded-[3px]", item.swatch)} />
              {item.label}
            </span>
          ))}
          {t("users.heroesCompare.table.legendTail")}
        </span>
        <SearchField
          value={query}
          onValueChange={onQueryChange}
          label={t("users.heroesCompare.filters.searchPlayer")}
          placeholder={t("users.heroesCompare.filters.searchPlayer")}
          containerClassName="w-full md:ml-auto md:w-64"
          className="max-md:h-10"
        />
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onResetColumns}
          title={t("users.heroesCompare.filters.resetColumnsTitle")}
        >
          <RotateCcw aria-hidden />
          {t("users.heroesCompare.filters.resetColumns")}
        </Button>
      </div>

      {/* One table, one row order: column k and column k+1 describe the same player. */}
      <div className="overflow-x-auto">
        <table
          aria-labelledby={TITLE_ID}
          aria-busy={isLoading}
          className="w-full min-w-[960px] table-fixed border-separate border-spacing-0"
        >
          <colgroup>
            <col className="w-[52px]" />
            {/* Narrower on a phone: the sticky rank + player pair must leave room for the column scrolling past. */}
            <col className="w-[156px] sm:w-[230px]" />
            <col className="w-[88px]" />
            {columnKeys.map((key, i) => (
              <col key={`${key}-${i}`} />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th scope="col" className={cn(HEAD_CELL, STICKY_RANK)}>
                <span className="sr-only">{t("users.heroesCompare.table.rank")}</span>
              </th>
              <th scope="col" className={cn(HEAD_CELL, STICKY_PLAYER, eyebrowClass(), "text-left")}>
                {t("users.heroesCompare.table.player")}
              </th>
              <th scope="col" className={cn(HEAD_CELL, eyebrowClass(), "text-right")}>
                {t("users.heroesCompare.table.games")}
              </th>
              {columnKeys.map((key, i) => (
                <StatColumnHeader
                  key={`${key}-${i}`}
                  def={COL[key]}
                  options={ALL_STAT_OPTIONS}
                  isActive={i === sortIndex}
                  sortDir={sortDir}
                  onSort={() => onSortChange(i)}
                  onSelect={(k) => onColumnSelect(i, k)}
                />
              ))}
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              Array.from({ length: SKELETON_ROWS }).map((_, r) => (
                <tr key={r}>
                  {Array.from({ length: columnKeys.length + 3 }).map((__, c) => (
                    <td key={c} className={CELL}>
                      <Skeleton className="h-4 w-full" />
                    </td>
                  ))}
                </tr>
              ))
            ) : rows.length === 0 ? (
              <tr>
                <td
                  colSpan={columnKeys.length + 3}
                  className="py-[90px] text-center text-sm text-[color:var(--aqt-fg-dim)]"
                >
                  <span className="inline-flex items-center gap-2">
                    <Sword aria-hidden className="h-4 w-4 opacity-40" />
                    {emptyMessage}
                  </span>
                </td>
              </tr>
            ) : (
              rows.map((entry) => (
                <LeaderboardRow
                  key={entry.entry.user_id}
                  ranked={entry}
                  cells={cells}
                  grid={
                    (entry.entry.division_grid_version_id == null
                      ? undefined
                      : gridById.get(entry.entry.division_grid_version_id)) ?? divisionGrid
                  }
                  discipline={discipline}
                  isHighlighted={entry.entry.user_id === hoveredUserId}
                  onHoverUser={setHoveredUserId}
                />
              ))
            )}
          </tbody>
        </table>
      </div>

      {!isLoading && (rows.length > 0 || hiddenCount > 0) ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3 text-caption text-[color:var(--aqt-fg-dim)]">
          {hiddenCount > 0 ? (
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <EyeOff aria-hidden className="size-3.5 shrink-0 text-[color:var(--aqt-fg-faint)]" />
              {t("users.heroesCompare.table.belowFloor", { count: hiddenCount, min: minGames })}
              <Button
                type="button"
                variant="link"
                size="inline"
                onClick={onShowHidden}
                className="text-[color:var(--aqt-teal)]"
              >
                {t("users.heroesCompare.table.showBelowFloor")}
              </Button>
            </p>
          ) : null}
          {rows.length > 0 ? (
            <span className="ml-auto tabular-nums">
              {t("users.heroesCompare.table.showing", { shown: rows.length, total: matchCount })}
            </span>
          ) : null}
          {moreCount > 0 ? (
            <Button type="button" variant="outline" size="sm" onClick={onShowMore}>
              {t("users.heroesCompare.table.showMore", { count: moreCount })}
            </Button>
          ) : null}
        </div>
      ) : null}
    </section></Card>
  );
};

export default HeroLeaderboardTable;
