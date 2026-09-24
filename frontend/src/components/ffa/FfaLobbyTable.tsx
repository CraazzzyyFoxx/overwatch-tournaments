"use client";

import React from "react";
import { useTranslations } from "next-intl";

import TeamName from "@/components/TeamName";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { straddlingTieGroups } from "@/lib/tournament/tie-clusters";
import { cn } from "@/lib/utils";
import type { FfaLobby, FfaLobbyRow } from "@/types/ffa.types";

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

  const advanceCount = lobby.advance_count;
  const showCut = advanceCount != null && rows.length > advanceCount;
  const tiedAtCut =
    advanceCount == null
      ? new Set<number>()
      : straddlingTieGroups(
          rows.map((row) => ({
            position: row.position ?? Number.MAX_SAFE_INTEGER,
            tie_group: row.tie_group
          })),
          advanceCount
        );

  // The series length, not the games entered so far: an organizer resizes the
  // lobby with `games-count`, and the empty columns are what say how many
  // games are still to come.
  const positions = Array.from({ length: Math.max(lobby.best_of, 1) }, (_, index) => index + 1);
  const scoreLabel = lobby.rules.score_label?.trim() || t("ffa.colScore");
  const columnCount = 5 + positions.length + (advanceCount == null ? 0 : 1);
  const tieClusterTitle = t("ffa.tieCluster");
  const tieVerdictTitle = t("ffa.tieDecidesAdvance");

  return (
    <Table aria-label={t("ffa.tableLabel", { lobby: lobby.name })}>
      <TableHeader>
        <TableRow>
          <TableHead scope="col" className="w-[52px] whitespace-nowrap">
            <span className="sr-only">{t("ffa.colPlace")}</span>
            <span aria-hidden>#</span>
          </TableHead>
          <TableHead scope="col" className="min-w-[180px]">
            {t("ffa.colTeam")}
          </TableHead>
          <TableHead scope="col" className="text-right">
            {t("ffa.colPoints")}
          </TableHead>
          <TableHead scope="col" className="text-right">
            {t("ffa.colGames")}
          </TableHead>
          <TableHead scope="col" className="text-right whitespace-nowrap">
            {scoreLabel}
          </TableHead>
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
          {advanceCount != null && (
            <TableHead scope="col" className="text-center">
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
              advancing={advanceCount != null && row.position != null && row.position <= advanceCount}
              tied={row.tie_group != null && tiedAtCut.has(row.tie_group)}
              showStatus={advanceCount != null}
              clusterTitle={tieClusterTitle}
              verdictTitle={tieVerdictTitle}
            />
            {showCut && index === advanceCount - 1 && (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={columnCount} className="p-0" data-ffa-cut>
                  <span className="flex items-center gap-3 px-2 py-1.5 text-label font-bold uppercase tracking-label text-[color:var(--aqt-teal)]">
                    <span
                      aria-hidden
                      className="h-px flex-1 bg-[color:color-mix(in_srgb,var(--aqt-teal)_40%,transparent)]"
                    />
                    {t("common.topAdvance", { count: advanceCount })}
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
  );
}

function LobbyRow({
  row,
  positions,
  advancing,
  tied,
  showStatus,
  clusterTitle,
  verdictTitle
}: Readonly<{
  row: FfaLobbyRow;
  positions: number[];
  advancing: boolean;
  tied: boolean;
  showStatus: boolean;
  clusterTitle: string;
  verdictTitle: string;
}>) {
  const t = useTranslations();
  const gameAt = new Map(row.games.map((cell) => [cell.position, cell]));

  return (
    <TableRow
      data-advancing={advancing ? "" : undefined}
      data-tie={tied ? "" : undefined}
      className={cn(
        // The tie wins the tint: the line cuts through the cluster, so
        // "advancing" is a promise the lobby's results have not made.
        tied
          ? "bg-[color:color-mix(in_srgb,var(--aqt-amber)_8%,transparent)]"
          : advancing
            ? "bg-[color:color-mix(in_srgb,var(--aqt-teal)_5%,transparent)]"
            : undefined
      )}
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
          title={row.tie_group != null ? clusterTitle : undefined}
        >
          {row.tie_group ?? row.position ?? "—"}
        </span>
      </TableCell>
      <TableCell>
        <TeamName team={{ name: row.team_name, image_url: row.team_image_url }} size="xs" />
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
              <span className="inline-flex flex-col items-center leading-tight">
                <span className="aqt-tnum text-caption font-semibold text-[color:var(--aqt-fg)]">
                  {cell.placement ?? "—"}
                </span>
                {cell.score != null && (
                  <span className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]">
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
            title={tied ? verdictTitle : undefined}
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
