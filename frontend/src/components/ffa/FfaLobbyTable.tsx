"use client";

import React from "react";
import { useTranslations } from "next-intl";

import TeamName from "@/components/TeamName";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { straddlingTieGroups } from "@/lib/tournament/tie-clusters";
import { cn } from "@/lib/utils";
import type { FfaLobby, FfaLobbyRow } from "@/types/ffa.types";

/**
 * Every game position the lobby has a cell for.
 *
 * Normally `1..best_of`, but NOT only that: `_read_lobby` (backend
 * `services/encounter/ffa.py`) answers `max(best_of, …recorded positions)`
 * columns on purpose. Lowering a lobby's games count does not delete the games
 * already played past the new end — they stay confirmed and keep scoring, and
 * voiding one is the only way to finish lowering the count. Sizing this from
 * `best_of` alone hid a counted game from the table while the organizer's own
 * void button for it sat right underneath.
 */
export function lobbyGamePositions(lobby: FfaLobby): number[] {
  let last = Math.max(lobby.best_of, 1);
  for (const row of lobby.rows) {
    for (const cell of row.games) {
      if (cell.position > last) last = cell.position;
    }
  }
  return Array.from({ length: last }, (_, index) => index + 1);
}

/**
 * One FFA lobby, as its standings.
 *
 * A lobby has no second screen: the group's table IS this table, so it carries
 * everything a group standings table carries — the advance line, the tie
 * clusters that line runs through, the per-game record — with the lobby's own
 * `advance_count` rather than a stage-wide guess.
 *
 * Zone-neutral on purpose (docs/frontend-zones.md): the public bracket, the
 * public lobby page and the organizer's lobby editor all render the same
 * table, so it reaches into neither `src/components/admin` nor `src/app`, and
 * it styles itself from the shared `ui/table` primitive rather than from the
 * `.aqt-tn`-scoped rules that only exist under the tournament shell.
 */
export default function FfaLobbyTable({ lobby }: Readonly<{ lobby: FfaLobby }>) {
  const t = useTranslations();

  // `position` is null until the standings job has ranked the group once; those
  // rows keep their seating order at the bottom rather than jumping to the top.
  const rows = [...lobby.rows].sort(
    (left, right) =>
      (left.position ?? Number.MAX_SAFE_INTEGER) - (right.position ?? Number.MAX_SAFE_INTEGER) ||
      left.slot - right.slot
  );

  // Before the first game counts, every team is level on every tiebreaker, so
  // the engine answers one cluster holding the whole lobby. Printed as-is that
  // is "everyone 1st" and, under a cut line, "the assigned order decides who
  // advances" — claims about a lobby nobody has played. No ranks, no verdicts
  // until there are results to rank by; the cut line stays, it is the rule.
  const ranked = rows.some((row) => row.games_played > 0);

  const advanceCount = lobby.advance_count;
  const showCut = advanceCount != null && rows.length > advanceCount;
  const showStatus = advanceCount != null && ranked;
  const tiedAtCut =
    advanceCount == null || !ranked
      ? new Set<number>()
      : straddlingTieGroups(
          rows.map((row) => ({
            position: row.position ?? Number.MAX_SAFE_INTEGER,
            tie_group: row.tie_group
          })),
          advanceCount
        );

  // The whole series, not the games entered so far: the empty columns are what
  // say how many games are still to come.
  const positions = lobbyGamePositions(lobby);
  const scoreLabel = lobby.rules.score_label?.trim() || t("ffa.colScore");
  const columnCount = 5 + positions.length + (showStatus ? 1 : 0);

  // What turns a game cell and the points column back into numbers a reader
  // can check: the lobby's own rules, not a stage-wide description.
  const placementPoints = lobby.rules.placement_points.join(" · ");
  const multiplier = lobby.rules.score_points;
  const pointsLegend =
    placementPoints && multiplier
      ? t("ffa.legendPoints", { placements: placementPoints, label: scoreLabel, multiplier })
      : placementPoints
        ? t("ffa.legendPointsPlacement", { placements: placementPoints })
        : multiplier
          ? t("ffa.legendPointsScore", { label: scoreLabel, multiplier })
          : null;

  return (
    <div>
      <Table aria-label={t("ffa.tableLabel", { lobby: lobby.name })}>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead scope="col" className="w-[52px] whitespace-nowrap">
              <span className="sr-only">{t("ffa.colPlace")}</span>
              <span aria-hidden>#</span>
            </TableHead>
            <TableHead scope="col" className={cn(STICKY_TEAM, "min-w-[9rem] bg-card")}>
              {t("ffa.colTeam")}
            </TableHead>
            <TableHead scope="col" className="w-16 text-right">
              {t("ffa.colPoints")}
            </TableHead>
            <TableHead scope="col" className="w-16 text-right">
              {t("ffa.colGames")}
            </TableHead>
            <TableHead scope="col" className="w-20 text-right whitespace-nowrap">
              {scoreLabel}
            </TableHead>
            {positions.map((position) => (
              <TableHead
                key={position}
                scope="col"
                className="w-12 text-center whitespace-nowrap"
                // The visible text is an abbreviation; assistive technology gets
                // the spelled-out game number.
                aria-label={t("ffa.gameLabel", { position })}
                title={t("ffa.gameLabel", { position })}
              >
                {t("ffa.colGame", { position })}
              </TableHead>
            ))}
            {showStatus && (
              <TableHead scope="col" className="w-20 text-center">
                <span className="sr-only">{t("common.status")}</span>
              </TableHead>
            )}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <React.Fragment key={row.team_id}>
              <LobbyRow
                row={row}
                positions={positions}
                ranked={ranked}
                advancing={showStatus && row.position != null && row.position <= advanceCount}
                tied={row.tie_group != null && tiedAtCut.has(row.tie_group)}
                showStatus={showStatus}
                scoreLabel={scoreLabel}
              />
              {showCut && index === advanceCount - 1 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={columnCount} className="p-0" data-ffa-cut>
                    <span className="flex items-center gap-3 px-2 py-1.5 text-label font-bold uppercase tracking-label text-[color:var(--aqt-teal)]">
                      {/* Leading and sticky, not centred: on a phone the table
                          scrolls sideways and a centred label sat off-screen. */}
                      <span className="sticky left-2 whitespace-nowrap">
                        {t("common.topAdvance", { count: advanceCount })}
                      </span>
                      <span
                        aria-hidden
                        className="h-px flex-1 bg-[color:color-mix(in_srgb,var(--aqt-teal)_40%,transparent)]"
                      />
                    </span>
                  </TableCell>
                </TableRow>
              )}
            </React.Fragment>
          ))}
        </TableBody>
      </Table>
      <p className="flex flex-wrap gap-x-4 gap-y-1 px-2 pt-3 text-caption text-[color:var(--aqt-fg-dim)]">
        <span>{t("ffa.legendCells", { label: scoreLabel })}</span>
        {pointsLegend && <span>{pointsLegend}</span>}
      </p>
    </div>
  );
}

/**
 * The team column stays put while the numbers scroll under it on a phone.
 * The row line is redrawn on the cell: a positioned cell paints above the
 * collapsed `tr` border, which erased the line under every team name.
 */
const STICKY_TEAM =
  "sticky left-0 z-[1] shadow-[inset_0_-1px_hsl(var(--border))] [tbody_tr:last-child_&]:shadow-none";

/**
 * Row backgrounds are OPAQUE mixes over the card, not alpha tints: the sticky
 * team cell inherits its row's background and has to hide the columns that
 * scroll under it. `--card` is the surface every host paints the table on —
 * the public bracket and lobby page through `--aqt-card` (the same value), the
 * organizer's `Card` directly, in either theme. Hover deepens the tint instead
 * of swapping it for the primitive's neutral one, as the group table does.
 */
const ROW_TONE = {
  tie: "bg-[color:color-mix(in_srgb,var(--aqt-amber)_8%,hsl(var(--card)))] hover:bg-[color:color-mix(in_srgb,var(--aqt-amber)_13%,hsl(var(--card)))]",
  advancing:
    "bg-[color:color-mix(in_srgb,var(--aqt-teal)_5%,hsl(var(--card)))] hover:bg-[color:color-mix(in_srgb,var(--aqt-teal)_9%,hsl(var(--card)))]",
  none: "bg-card hover:bg-[color:color-mix(in_srgb,hsl(var(--foreground))_4%,hsl(var(--card)))]"
} as const;

function LobbyRow({
  row,
  positions,
  ranked,
  advancing,
  tied,
  showStatus,
  scoreLabel
}: Readonly<{
  row: FfaLobbyRow;
  positions: number[];
  ranked: boolean;
  advancing: boolean;
  tied: boolean;
  showStatus: boolean;
  scoreLabel: string;
}>) {
  const t = useTranslations();
  const gameAt = new Map(row.games.map((cell) => [cell.position, cell]));
  const clustered = ranked && row.tie_group != null;

  return (
    <TableRow
      data-advancing={advancing ? "" : undefined}
      data-tie={tied ? "" : undefined}
      // The tie wins the tint: the line cuts through the cluster, so
      // "advancing" is a promise the lobby's results have not made.
      className={tied ? ROW_TONE.tie : advancing ? ROW_TONE.advancing : ROW_TONE.none}
    >
      <TableCell className="whitespace-nowrap">
        {/* Every row of a cluster prints its head's position, so 2/2/4 reads
            as "these two were never separated". */}
        <span
          data-ffa-rank
          className={cn(
            "aqt-tnum text-title font-bold leading-none",
            tied
              ? "text-[color:var(--aqt-amber)]"
              : advancing
                ? "text-[color:var(--aqt-teal)]"
                : "text-[color:var(--aqt-fg-faint)]"
          )}
        >
          {ranked ? (row.tie_group ?? row.position ?? "—") : "—"}
        </span>
        {clustered && (
          <>
            <span aria-hidden className="ml-0.5 text-[color:var(--aqt-fg-dim)]" title={t("ffa.tieCluster")}>
              =
            </span>
            <span className="sr-only">{t("ffa.tieCluster")}</span>
          </>
        )}
      </TableCell>
      <TableCell className={cn(STICKY_TEAM, "bg-inherit")}>
        <TeamName
          team={{ name: row.team_name, image_url: row.team_image_url }}
          size="xs"
          className="max-w-[9rem] sm:max-w-none"
          nameClassName="font-semibold text-[color:var(--aqt-fg)]"
        />
      </TableCell>
      <TableCell className="aqt-tnum text-right text-[color:var(--aqt-fg)]">
        {row.points.toFixed(1)}
      </TableCell>
      <TableCell className="aqt-tnum text-right text-[color:var(--aqt-fg-dim)]">
        {row.games_played}
      </TableCell>
      <TableCell className="aqt-tnum text-right text-[color:var(--aqt-fg-muted)]">
        {row.score}
      </TableCell>
      {positions.map((position) => {
        const cell = gameAt.get(position);
        return (
          <TableCell key={position} className="text-center" data-ffa-game={position}>
            {/* A game nobody has entered renders NOTHING. A `0` here would read
                as "played it, scored nothing" — a different claim entirely. */}
            {cell?.state == null ? null : (
              // Two bare numbers read aloud as "3 6"; each carries the label its
              // column would, had the cell room for two headers.
              <span className="inline-flex flex-col items-center leading-tight">
                <span className="aqt-tnum text-caption font-semibold text-[color:var(--aqt-fg)]">
                  <span className="sr-only">{t("ffa.colPlace")} </span>
                  {cell.placement ?? "—"}
                </span>
                {cell.score != null && (
                  <span className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]">
                    <span className="sr-only">{scoreLabel} </span>
                    {cell.score}
                  </span>
                )}
              </span>
            )}
          </TableCell>
        );
      })}
      {showStatus && (
        <TableCell className="text-center">
          <span
            data-ffa-status
            title={tied ? t("ffa.tieDecidesAdvance") : undefined}
            className={cn(
              "inline-flex items-center rounded px-2 py-0.5 text-label font-bold uppercase tracking-label",
              tied
                ? "bg-[color:color-mix(in_srgb,var(--aqt-amber)_14%,transparent)] text-[color:var(--aqt-amber)]"
                : advancing
                  ? "bg-[color:color-mix(in_srgb,var(--aqt-teal)_14%,transparent)] text-[color:var(--aqt-teal)]"
                  : "bg-[color:var(--aqt-overlay-2)] text-[color:var(--aqt-fg-dim)]"
            )}
          >
            {tied ? t("ffa.tieStatus") : advancing ? t("ffa.advancing") : t("ffa.eliminated")}
          </span>
        </TableCell>
      )}
    </TableRow>
  );
}
