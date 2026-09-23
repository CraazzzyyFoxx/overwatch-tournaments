"use client";

import { useMemo, useState } from "react";
import { Sword } from "lucide-react";
import { useTranslations } from "next-intl";

import { Hero, HeroLeaderboardEntry } from "@/types/hero.types";
import HeroImage from "@/components/hero/HeroImage";
import { heroVariantFromRole } from "@/lib/roster/player-role";
import { Skeleton } from "@/components/ui/skeleton";

import { COL, StatKey, ALL_STAT_OPTIONS } from "../config/stat-columns";
import { teamDotBackground } from "../utils/teamColor";
import BarRow, { type StatCellSpec } from "./BarRow";
import StatColumnHeader from "./StatColumnHeader";

const MAX_LEGEND_TEAMS = 12;
const SKELETON_ROWS = 15;
const TITLE_ID = "hero-leaderboard-title";

const CELL = "border-b border-[color:var(--aqt-border)] px-3.5 py-2";
const HEAD_CELL =
  "border-b border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.008)] px-3.5 pb-3 pt-3.5 align-bottom";

interface HeroLeaderboardTableProps {
  selectedHero: Hero | undefined;
  selectedTournamentName: string | undefined;
  tournamentId: number | undefined;
  rows: HeroLeaderboardEntry[];
  isLoading: boolean;
  columnKeys: StatKey[];
  /** Index into `columnKeys` of the column that drives the shared row order. */
  sortIndex: number;
  sortDir: "asc" | "desc";
  onColumnSelect: (colIndex: number, key: StatKey) => void;
  onSortChange: (colIndex: number) => void;
}

const HeroLeaderboardTable = ({
  selectedHero,
  selectedTournamentName,
  tournamentId,
  rows,
  isLoading,
  columnKeys,
  sortIndex,
  sortDir,
  onColumnSelect,
  onSortChange,
}: HeroLeaderboardTableProps) => {
  const t = useTranslations();
  const [hoveredUserId, setHoveredUserId] = useState<number | null>(null);
  const variant = heroVariantFromRole(selectedHero?.type ?? selectedHero?.role);

  // One bar scale per column, computed over the whole roster (not per row), so
  // the scale is independent of the shared sort order.
  const cells = useMemo<StatCellSpec[]>(
    () =>
      columnKeys.map((key) => {
        const def = COL[key];
        if (rows.length === 0) return { def, minValue: 0, maxValue: 1 };
        let min = Infinity;
        let max = -Infinity;
        for (const r of rows) {
          const v = def.getValue(r);
          if (v < min) min = v;
          if (v > max) max = v;
        }
        return { def, minValue: min, maxValue: max || 1 };
      }),
    [columnKeys, rows]
  );

  // Single row order for every column: reading across a row is one player.
  const sortedRows = useMemo(() => {
    const def = COL[columnKeys[sortIndex]] ?? COL[columnKeys[0]];
    const dir = sortDir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => (def.getValue(a) - def.getValue(b)) * dir);
  }, [rows, columnKeys, sortIndex, sortDir]);

  const legendTeams = useMemo(() => {
    const seen = new Map<string, { team: string; teamId: number | null }>();
    for (const r of rows) {
      if (r.team && !seen.has(r.team)) seen.set(r.team, { team: r.team, teamId: r.team_id });
    }
    return Array.from(seen.values());
  }, [rows]);

  return (
    <section className="overflow-hidden rounded-[var(--aqt-radius)] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]">
      {/* Board head */}
      <div className="flex items-center gap-3.5 border-b border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.012)] px-5 py-4">
        {selectedHero && <HeroImage hero={selectedHero} size={44} rounded="lg" />}
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <h2
              id={TITLE_ID}
              className="font-[family-name:var(--aqt-display)] text-2xl font-bold uppercase leading-none tracking-[0.03em]"
            >
              {selectedHero?.name ?? t("users.heroesCompare.table.heroFallback")}
            </h2>
            {selectedHero && (
              <span
                className="rounded-[5px] px-1.5 py-0.5 text-label font-bold uppercase leading-none tracking-label"
                style={{
                  color: `var(--aqt-${variant})`,
                  background: `color-mix(in srgb, var(--aqt-${variant}) 15%, transparent)`,
                }}
              >
                {selectedHero.type ?? selectedHero.role}
              </span>
            )}
          </div>
          <p className="mt-1 font-[family-name:var(--aqt-data)] text-label text-[color:var(--aqt-fg-dim)]">
            {selectedTournamentName ?? t("users.heroesCompare.allTournaments")}
            {tournamentId ? ` · ${t("users.heroesCompare.table.scope")} #${tournamentId}` : ""}
          </p>
        </div>
        {!isLoading && rows.length > 0 && (
          <span className="ml-auto rounded-full border border-[color:var(--aqt-border-2)] bg-[hsl(0_0%_100%/0.03)] px-[11px] py-[5px] font-[family-name:var(--aqt-data)] text-label tabular-nums text-[color:var(--aqt-fg-muted)]">
            {t.rich("users.heroesCompare.table.playersCount", {
              count: rows.length,
              em: (chunks) => (
                <em className="not-italic font-semibold text-[color:var(--aqt-teal)]">{chunks}</em>
              )
            })}
          </span>
        )}
      </div>

      {/* One table, one row order — column k and column k+1 describe the same player. */}
      <div className="overflow-x-auto">
        <table
          aria-labelledby={TITLE_ID}
          aria-busy={isLoading}
          className="w-full min-w-[1140px] table-fixed border-collapse"
        >
          <colgroup>
            <col className="w-[44px]" />
            <col className="w-[150px]" />
            {columnKeys.map((key, i) => (
              <col key={`${key}-${i}`} className="w-[189px]" />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th scope="col" className={`${HEAD_CELL} text-center`}>
                <span className="sr-only">{t("users.heroesCompare.table.rank")}</span>
              </th>
              <th
                scope="col"
                className={`${HEAD_CELL} text-left text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]`}
              >
                {t("users.heroesCompare.table.player")}
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
                  <td className={CELL}>
                    <Skeleton className="h-4 w-full" />
                  </td>
                  <td className={CELL}>
                    <Skeleton className="h-4 w-full" />
                  </td>
                  {columnKeys.map((key, i) => (
                    <td key={`${key}-${i}`} className={CELL}>
                      <Skeleton className="h-5 w-full" />
                    </td>
                  ))}
                </tr>
              ))
            ) : sortedRows.length === 0 ? (
              <tr>
                <td
                  colSpan={columnKeys.length + 2}
                  className="py-[90px] text-center text-sm text-[color:var(--aqt-fg-dim)]"
                >
                  <span className="inline-flex items-center gap-2">
                    <Sword aria-hidden className="h-4 w-4 opacity-40" />
                    {tournamentId
                      ? t("users.heroesCompare.table.noDataInTournament")
                      : t("users.heroesCompare.table.noData")}
                  </span>
                </td>
              </tr>
            ) : (
              sortedRows.map((entry, i) => (
                <BarRow
                  key={entry.user_id}
                  entry={entry}
                  rank={i + 1}
                  cells={cells}
                  isHighlighted={entry.user_id === hoveredUserId}
                  onHoverUser={setHoveredUserId}
                />
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Teams legend */}
      {!isLoading && legendTeams.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-t border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.008)] px-5 py-3 text-label text-[color:var(--aqt-fg-dim)]">
          <span className="text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
            {t("common.teams")}
          </span>
          {legendTeams.slice(0, MAX_LEGEND_TEAMS).map(({ team, teamId }) => (
            <span key={team} className="inline-flex items-center gap-1.5 font-[family-name:var(--aqt-data)] text-[color:var(--aqt-fg-muted)]">
              <span
                aria-hidden
                className="h-[9px] w-[9px] rounded-[2px]"
                style={{ background: teamDotBackground(team, teamId) }}
              />
              {team}
            </span>
          ))}
          {legendTeams.length > MAX_LEGEND_TEAMS && (
            <span className="text-[color:var(--aqt-fg-faint)]">+{legendTeams.length - MAX_LEGEND_TEAMS} {t("common.more")}</span>
          )}
        </div>
      )}
    </section>
  );
};

export default HeroLeaderboardTable;
