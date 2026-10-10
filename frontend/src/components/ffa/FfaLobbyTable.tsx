"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { Lock } from "lucide-react";

import TeamName from "@/components/TeamName";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { straddlingTieGroups } from "@/lib/tournament/tie-clusters";
import { cn } from "@/lib/utils";
import type { FfaColumn, FfaGameCell, FfaLobby, FfaLobbyRow } from "@/types/ffa.types";

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
 * A number the organizer entered or the formula produced, printed as written.
 *
 * Game points are a custom expression rounded to four decimals server-side, so
 * a fixed width is wrong in both directions: `16.0` beside a place number is
 * noise, and `12` in place of `12.5` is a different number. Two decimals is
 * what a game cell holds; trailing zeros are dropped so the common whole number
 * stays one token wide. The Pts column keeps its own `toFixed(1)` — a season
 * total is read down a column, where a ragged decimal point is the noise.
 */
function formatFfaNumber(value: number): string {
  return String(Number(value.toFixed(2)));
}

/**
 * Medal tones for places 1-3; everything below stays neutral. Full class
 * strings (not built from the place) so Tailwind sees every one of them.
 */
const MEDAL_TEXT: Record<number, string> = {
  1: "text-[color:var(--aqt-gold)]",
  2: "text-[color:var(--aqt-silver)]",
  3: "text-[color:var(--aqt-bronze)]"
};

const MEDAL_CHIP: Record<number, string> = {
  1: "bg-[color:color-mix(in_srgb,var(--aqt-gold)_16%,transparent)] text-[color:var(--aqt-gold)]",
  2: "bg-[color:color-mix(in_srgb,var(--aqt-silver)_14%,transparent)] text-[color:var(--aqt-silver)]",
  3: "bg-[color:color-mix(in_srgb,var(--aqt-bronze)_16%,transparent)] text-[color:var(--aqt-bronze)]"
};

/**
 * One played game: the place as a medal-toned chip, the points it paid below.
 *
 * Two stacked bare numbers are read aloud as "3 16" and say nothing about where
 * 16 came from, so the cell carries ONE sentence — place, points and every
 * public value of that game — as its `title` and as the only thing a screen
 * reader is given. The visible numbers are `aria-hidden` rather than labelled
 * one by one: labelled, the cell would announce the place, then the points,
 * then the very same numbers again inside the description.
 */
function GameCell({ cell, columns }: Readonly<{ cell: FfaGameCell; columns: FfaColumn[] }>) {
  const t = useTranslations();
  const parts = [`${t("ffa.colPlace")} ${cell.placement ?? "—"}`];
  if (cell.points != null) parts.push(`${t("ffa.colPoints")} ${formatFfaNumber(cell.points)}`);
  for (const column of columns) {
    const value = cell.stats?.[column.key];
    if (value != null) parts.push(`${column.label} ${formatFfaNumber(value)}`);
  }
  const description = parts.join(", ");

  return (
    <span className="inline-flex flex-col items-center gap-1" title={description}>
      <span
        aria-hidden
        className={cn(
          "aqt-tnum inline-flex size-7 items-center justify-center rounded-md text-caption font-bold",
          (cell.placement != null && MEDAL_CHIP[cell.placement]) ||
            "text-[color:var(--aqt-fg-dim)] ring-1 ring-inset ring-[color:var(--aqt-border)]"
        )}
      >
        {cell.placement ?? "—"}
      </span>
      {cell.points != null && (
        <span aria-hidden className="aqt-tnum text-label leading-none text-[color:var(--aqt-fg-faint)]">
          {formatFfaNumber(cell.points)}
        </span>
      )}
      <span className="sr-only">{description}</span>
    </span>
  );
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
  // Only the organizer's PUBLIC columns are printed, and the filter lives here
  // rather than at the read: this one component renders the public bracket, the
  // public lobby page AND the organizer's lobby editor, and the editor feeds it
  // the admin read, which still carries the hidden columns. Filtering at the
  // component is what makes "a spectator never sees a hidden value" a property
  // of the markup instead of a property of whoever picked the endpoint.
  const columns = lobby.rules.columns.filter((column) => column.public);
  // `5`: rank, team, points, games and the trailing filler cell.
  const columnCount = 5 + columns.length + positions.length + (showStatus ? 1 : 0);

  // What turns the numbers back into something a reader can check: the rule
  // this lobby was actually scored by, printed as the organizer wrote it.
  const placementPoints = lobby.rules.placement_points.join(" / ");

  return (
    <div>
      {/* Column spacing is the cell padding alone: 40px between columns
          (`px-5`, the primitive has 16px). Widths on the cells would be dead,
          the trailing filler cell takes every pixel of slack. */}
      <Table
        aria-label={t("ffa.tableLabel", { lobby: lobby.name })}
        className="[&_td]:px-5 [&_th]:px-5"
      >
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead scope="col" className="whitespace-nowrap">
              <span className="sr-only">{t("ffa.colPlace")}</span>
              <span aria-hidden>#</span>
            </TableHead>
            <TableHead scope="col" className={cn(STICKY_TEAM, "min-w-[9rem] bg-card")}>
              {t("ffa.colTeam")}
            </TableHead>
            <TableHead scope="col" className="text-right text-[color:var(--aqt-fg)]">
              {t("ffa.colPoints")}
            </TableHead>
            <TableHead scope="col" className="text-right">
              {t("ffa.colGames")}
            </TableHead>
            {columns.map((column) => (
              <TableHead
                key={column.key}
                scope="col"
                className="text-right whitespace-nowrap"
              >
                {column.label}
              </TableHead>
            ))}
            {positions.map((position) => (
              <TableHead
                key={position}
                scope="col"
                className="text-center whitespace-nowrap"
                // The visible text is an abbreviation; assistive technology gets
                // the spelled-out game number.
                aria-label={t("ffa.gameLabel", { position })}
                title={t("ffa.gameLabel", { position })}
              >
                {t("ffa.colGame", { position })}
              </TableHead>
            ))}
            {showStatus && (
              <TableHead scope="col" className="text-center">
                <span className="sr-only">{t("common.status")}</span>
              </TableHead>
            )}
            {/* Takes the slack width, so the numbers sit next to the team name
                instead of being pushed to the far edge. A `td`: it heads nothing. */}
            <TableCell aria-hidden className="w-full p-0" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <React.Fragment key={row.team_id}>
              <LobbyRow
                row={row}
                positions={positions}
                ranked={ranked}
                medals={ranked && advanceCount == null}
                advancing={showStatus && row.position != null && row.position <= advanceCount}
                tied={row.tie_group != null && tiedAtCut.has(row.tie_group)}
                showStatus={showStatus}
                columns={columns}
              />
              {showCut && index === advanceCount - 1 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={columnCount} className="p-0" data-ffa-cut>
                    <span className="flex items-center gap-3 py-1.5 text-label font-bold uppercase tracking-label text-[color:var(--aqt-teal)]">
                      {/* Leading and sticky, not centred: on a phone the table
                          scrolls sideways and a centred label sat off-screen. */}
                      <span className="sticky left-5 whitespace-nowrap">
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
      <p className="flex flex-wrap gap-x-4 gap-y-1 px-5 pt-2 text-caption text-[color:var(--aqt-fg-dim)]">
        <span>
          {t.rich("ffa.legendFormula", {
            formula: lobby.rules.formula,
            code: (chunks) => (
              <code className="font-[family-name:var(--aqt-data)] text-[color:var(--aqt-fg-muted)]">
                {chunks}
              </code>
            )
          })}
        </span>
        {placementPoints && (
          <span>{t("ffa.legendPlacement", { placements: placementPoints })}</span>
        )}
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
  columns,
  ranked,
  medals,
  advancing,
  tied,
  showStatus
}: Readonly<{
  row: FfaLobbyRow;
  positions: number[];
  /** The public columns, already filtered by the table. */
  columns: FfaColumn[];
  ranked: boolean;
  /** No advance line: the rank is plain standings, so the top three get medals. */
  medals: boolean;
  advancing: boolean;
  tied: boolean;
  showStatus: boolean;
}>) {
  const t = useTranslations();
  const gameAt = new Map(row.games.map((cell) => [cell.position, cell]));
  const clustered = ranked && row.tie_group != null;
  // Every row of a cluster prints its head's position, so 2/2/4 reads as
  // "these two were never separated".
  const rank = ranked ? (row.tie_group ?? row.position) : null;

  return (
    <TableRow
      data-advancing={advancing ? "" : undefined}
      data-tie={tied ? "" : undefined}
      // The tie wins the tint: the line cuts through the cluster, so
      // "advancing" is a promise the lobby's results have not made.
      className={tied ? ROW_TONE.tie : advancing ? ROW_TONE.advancing : ROW_TONE.none}
    >
      <TableCell className="whitespace-nowrap">
        <span
          data-ffa-rank
          className={cn(
            "aqt-tnum text-heading font-bold leading-none",
            tied
              ? "text-[color:var(--aqt-amber)]"
              : advancing
                ? "text-[color:var(--aqt-teal)]"
                : (medals && rank != null && MEDAL_TEXT[rank]) || "text-[color:var(--aqt-fg-faint)]"
          )}
        >
          {rank ?? "—"}
        </span>
        {clustered && (
          <>
            <span aria-hidden className="ml-0.5 text-[color:var(--aqt-fg-dim)]" title={t("ffa.tieCluster")}>
              =
            </span>
            <span className="sr-only">{t("ffa.tieCluster")}</span>
          </>
        )}
        {ranked && row.is_pinned && (
          <span
            className="ml-1 inline-flex align-[-0.125em] text-[color:var(--aqt-fg-dim)]"
            title={t("ffa.pinnedPlace")}
          >
            <Lock aria-hidden className="size-3" />
            <span className="sr-only">{t("ffa.pinnedPlace")}</span>
          </span>
        )}
      </TableCell>
      <TableCell className={cn(STICKY_TEAM, "bg-inherit whitespace-nowrap")}>
        <TeamName
          team={{ name: row.team_name, image_url: row.team_image_url }}
          size="xs"
          className="max-w-[9rem] sm:max-w-none"
          nameClassName="font-semibold text-[color:var(--aqt-fg)]"
        />
      </TableCell>
      <TableCell className="aqt-tnum text-right text-body font-bold text-[color:var(--aqt-fg)]">
        {row.points.toFixed(1)}
      </TableCell>
      <TableCell className="aqt-tnum text-right text-[color:var(--aqt-fg-dim)]">
        {row.games_played}
      </TableCell>
      {columns.map((column) => (
        <TableCell
          key={column.key}
          data-ffa-stat={column.key}
          className="aqt-tnum text-right text-[color:var(--aqt-fg-muted)]"
        >
          {/* A key the team never scored is absent from the totals, and absent
              means zero (spec §3.2) — a column added mid-stage must not blank
              out the games already played. */}
          {formatFfaNumber(row.stats[column.key] ?? 0)}
        </TableCell>
      ))}
      {positions.map((position) => {
        const cell = gameAt.get(position);
        return (
          <TableCell key={position} className="py-1.5 text-center" data-ffa-game={position}>
            {/* A game nobody has entered renders NOTHING. A `0` here would read
                as "played it, scored nothing" — a different claim entirely. */}
            {cell?.state == null ? null : <GameCell cell={cell} columns={columns} />}
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
      <TableCell aria-hidden className="p-0" />
    </TableRow>
  );
}
