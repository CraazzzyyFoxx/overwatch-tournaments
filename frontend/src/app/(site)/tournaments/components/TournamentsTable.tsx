"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import { useMinuteClock } from "@/hooks/useMinuteClock";
import { LayoutGrid } from "lucide-react";

import type { TeamFormation, Tournament } from "@/types/tournament.types";
import { formatDateRange } from "@/lib/datetime";
import { cn } from "@/lib/utils";
import { stageProgress } from "@/lib/tournament/stage-progress";
import { getTournamentStatusMeta } from "@/lib/tournament/status";
import { tournamentHref } from "@/lib/tournament/url";
import { TournamentStatusPill } from "@/components/tournaments/StatusPill";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { GameLabel } from "@/components/workspace/GameLabel";
import type { DisciplineDescriptor } from "@/types/discipline.types";

const CELL = "px-3.5 py-3.25";
const HEAD = "px-3.5";
const SEP = "mx-1.25 text-[color:var(--aqt-fg-faint)]";

const TournamentRow = ({
  tournament,
  games,
  now
}: {
  tournament: Tournament;
  games?: Map<string, DisciplineDescriptor>;
  now: number | null;
}) => {
  const t = useTranslations();
  const format = useFormatter();
  const { variant } = getTournamentStatusMeta(tournament.status);
  const stage = stageProgress(tournament, tournament.status, t);
  const players = tournament.participants_count ?? 0;

  return (
    <TableRow>
      <TableCell className={CELL}>
        <div className="flex min-w-45 flex-col gap-0.75">
          <span className="flex items-center gap-2 text-body leading-tight font-semibold text-[color:var(--aqt-fg)]">
            {/* A plain link on the name, not a row-wide `position:absolute`
                overlay. A `<tr>` is not a valid containing block for absolutely
                positioned children, so the overlay's width leaked past the
                table's scroll container and dragged the whole document sideways
                (+408px at 375px wide). The name link is the boring, correct
                target: focusable, announced, and contained. */}
            <Link
              href={tournamentHref(tournament)}
              className="rounded-xs hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
            >
              {tournament.name}
            </Link>
            {(tournament.status === "live" || tournament.status === "playoffs") && (
              <TournamentStatusPill status="live" className="px-[7px] py-0.5">
                {t("common.live")}
              </TournamentStatusPill>
            )}
            {tournament.is_hidden && (
              <TournamentStatusPill status="finished" className="px-[7px] py-0.5">
                {t("common.previewBadge")}
              </TournamentStatusPill>
            )}
          </span>
          <span className="text-label leading-tight text-[color:var(--aqt-fg-dim)]">
            {formatDateRange(format, tournament.start_date, tournament.end_date)}
            {games ? (
              <>
                <span className={SEP}>·</span>
                <GameLabel code={tournament.discipline} games={games} />
              </>
            ) : null}
            {tournament.is_league && (
              <>
                <span className={SEP}>·</span>
                {t("common.league")}
              </>
            )}
            {tournament.team_formation && (
              <>
                <span className={SEP}>·</span>
                {t(`common.${tournament.team_formation as TeamFormation}`)}
              </>
            )}
          </span>
        </div>
      </TableCell>
      <TableCell className={CELL}>
        <TournamentStatusPill status={variant}>
          {t(`common.statusBadge.${tournament.status}`)}
        </TournamentStatusPill>
      </TableCell>
      <TableCell className={CELL}>
        <div className="inline-flex items-center gap-2 text-label text-[color:var(--aqt-fg-muted)]">
          <span className="aqt-tnum min-w-16">{stage.label}</span>
          {/* The label beside it carries the stage; the bar only pictures it. */}
          <Progress aria-hidden size="sm" tone={stage.tone} value={stage.pct} className="w-20" />
        </div>
      </TableCell>
      <TableCell className={CELL}>
        <div className="flex min-w-15 flex-col gap-px">
          <span className="font-display text-heading leading-none font-bold tabular-nums text-[color:var(--aqt-fg)]">
            {players}
          </span>
          <span className="text-label leading-tight text-[color:var(--aqt-fg-dim)]">{t("common.players")}</span>
        </div>
      </TableCell>
      <TableCell className={cn(CELL, "text-right")}>
        <span className="aqt-tnum text-label text-[color:var(--aqt-fg-muted)]">
          {now !== null && format.relativeTime(new Date(tournament.updated_at ?? tournament.start_date), now)}
        </span>
      </TableCell>
      {/* One action, not two: the "open" arrow repeated the name link next to
          it, so every row cost keyboard users a second stop to the same page.
          The bracket is the shortcut the row cannot otherwise reach. The cell
          carries the quiet colour the ghost button keeps at rest. */}
      <TableCell className={cn(CELL, "text-right text-[color:var(--aqt-fg-faint)]")}>
        <Button asChild variant="ghost" size="icon">
          <Link
            href={tournamentHref(tournament, "/bracket")}
            aria-label={t("tournamentsList.row.bracketAria", { name: tournament.name })}
          >
            <LayoutGrid aria-hidden />
          </Link>
        </Button>
      </TableCell>
    </TableRow>
  );
};

/**
 * The list view. Renders exactly the tournaments it is handed: paging moved to
 * the page's infinite query, so slicing here would hide rows the page had
 * already fetched and counted.
 *
 * `className` is how the page hides it below `md`, where six columns cannot
 * fit and the cards are the only readable layout.
 */
const TournamentsTable = ({
  tournaments,
  games,
  className
}: {
  tournaments: Tournament[];
  games?: Map<string, DisciplineDescriptor>;
  className?: string;
}) => {
  const t = useTranslations();
  // One clock for the whole table, not an interval per row.
  const now = useMinuteClock();

  return (
    <Card asChild className={cn("overflow-hidden", className)}>
      <section data-tournament-table>
        {/* Labelled, focusable scroll region. Without it the 780px table is
            clipped by the card at narrow widths — the last three columns were
            simply unreachable on a phone — and the row-wide overlay link leaked
            its width into the document, scrolling the whole page sideways.
            `overscroll-x-contain` keeps a horizontal swipe inside the table
            instead of triggering browser back-navigation. `contain: paint` is
            load-bearing: a <table>'s intrinsic width propagates to the
            document's scroll width in Chromium even through an `overflow-x:
            auto` ancestor, so without it the table scrolls the whole page
            sideways at 375px. Safe here: nothing inside escapes its box, the
            actions are plain links and every overlay renders through a portal. */}
        <section
          className="overflow-x-auto overscroll-x-contain [contain:paint] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
          aria-label={t("common.tournaments")}
          tabIndex={0}
        >
          <Table wrapperClassName="overflow-visible" className="min-w-195">
            <TableHeader>
              <TableRow>
                <TableHead scope="col" className={HEAD}>
                  {t("common.tournament")}
                </TableHead>
                <TableHead scope="col" className={cn(HEAD, "w-30")}>
                  {t("common.status")}
                </TableHead>
                <TableHead scope="col" className={cn(HEAD, "w-42.5")}>
                  {t("common.stage")}
                </TableHead>
                <TableHead scope="col" className={cn(HEAD, "w-27.5")}>
                  {t("common.playersLabel")}
                </TableHead>
                <TableHead scope="col" className={cn(HEAD, "w-27.5 text-right")}>
                  {t("common.updated")}
                </TableHead>
                <TableHead scope="col" className={cn(HEAD, "w-20 text-right")}>
                  <span className="sr-only">{t("common.actions")}</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tournaments.map((tournament) => (
                <TournamentRow key={tournament.id} tournament={tournament} games={games} now={now} />
              ))}
            </TableBody>
          </Table>
        </section>
      </section>
    </Card>
  );
};

export default TournamentsTable;
