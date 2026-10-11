"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import { LayoutGrid } from "lucide-react";

import type { TeamFormation, Tournament } from "@/types/tournament.types";
import { formatDateRange } from "@/lib/datetime";
import { cn } from "@/lib/utils";
import { getTournamentStatusMeta } from "@/lib/tournament/status";
import { tournamentHref } from "@/lib/tournament/url";
import { TournamentStatusPill } from "@/components/tournaments/StatusPill";
import { stageProgress } from "./tournaments-helpers";

const TournamentRow = ({ tournament }: { tournament: Tournament }) => {
  const t = useTranslations();
  const format = useFormatter();
  const { variant } = getTournamentStatusMeta(tournament.status);
  const stage = stageProgress(tournament, tournament.status, t);
  const players = tournament.participants_count ?? 0;

  return (
    <tr>
      <td>
        <div className="tn-name-cell">
          <span className="nm">
            {/* A plain link on the name, not a row-wide `position:absolute`
                overlay. A `<tr>` is not a valid containing block for absolutely
                positioned children, so the overlay's width leaked past the
                table's scroll container and dragged the whole document sideways
                (+408px at 375px wide). The name link is the boring, correct
                target: focusable, announced, and contained. */}
            <Link
              href={tournamentHref(tournament)}
              className="rounded-[2px] outline-none hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
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
          <span className="sub">
            {formatDateRange(format, tournament.start_date, tournament.end_date)}
            {tournament.is_league && (
              <>
                <span className="sep">·</span>
                {t("common.league")}
              </>
            )}
            {tournament.team_formation && (
              <>
                <span className="sep">·</span>
                {t(`common.${tournament.team_formation as TeamFormation}`)}
              </>
            )}
          </span>
        </div>
      </td>
      <td>
        <span className={`tn-status ${variant}`}>
          <span aria-hidden className="dot" />
          {t(`common.statusBadge.${tournament.status}`)}
        </span>
      </td>
      <td>
        <div className="tn-stage">
          <span className="stage-label">{stage.label}</span>
          <div className="progress">
            <div
              className={cn(
                "fill",
                stage.fill === "amber" && "amber",
                stage.fill === "muted" && "muted"
              )}
              style={{ width: `${stage.pct}%` }}
            />
          </div>
        </div>
      </td>
      <td>
        <div className="tn-teams">
          <div className="stack">
            <span className="big tabular-nums">{players}</span>
            <span className="sub">{t("common.players")}</span>
          </div>
        </div>
      </td>
      <td className="r">
        <span className="aqt-tnum text-label text-[color:var(--aqt-fg-muted)]">
          {format.relativeTime(new Date(tournament.updated_at ?? tournament.start_date))}
        </span>
      </td>
      <td className="r">
        {/* One action, not two: the "open" arrow repeated the name link next to
            it, so every row cost keyboard users a second stop to the same page.
            The bracket is the shortcut the row cannot otherwise reach, and its
            box is forced inline because `.aqt-tn .icon-btn` (28px, shared with
            the detail pages) outranks any utility class. */}
        <div className="tn-actions">
          <Link
            href={tournamentHref(tournament, "/bracket")}
            className="icon-btn"
            style={{ width: 36, height: 36 }}
            aria-label={t("tournamentsList.row.bracketAria", { name: tournament.name })}
          >
            <LayoutGrid aria-hidden width={16} height={16} />
          </Link>
        </div>
      </td>
    </tr>
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
  className
}: {
  tournaments: Tournament[];
  className?: string;
}) => {
  const t = useTranslations();

  return (
    <section className={cn("tn-card", className)}>
      {/* Labelled, focusable scroll region. Without it the 780px table is
          clipped by the card at narrow widths — the last three columns were
          simply unreachable on a phone — and the row-wide overlay link leaked
          its width into the document, scrolling the whole page sideways. */}
      <section
        className="tn-table-scroll"
        aria-label={t("common.tournaments")}
        tabIndex={0}
      >
        <table className="tn">
        <thead>
          <tr>
            <th scope="col">{t("common.tournament")}</th>
            <th scope="col" style={{ width: 120 }}>
              {t("common.status")}
            </th>
            <th scope="col" style={{ width: 170 }}>
              {t("common.stage")}
            </th>
            <th scope="col" style={{ width: 110 }}>
              {t("common.playersLabel")}
            </th>
            <th scope="col" className="r" style={{ width: 110 }}>
              {t("common.updated")}
            </th>
            <th scope="col" className="r" style={{ width: 80 }}>
              <span className="sr-only">{t("common.actions")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {tournaments.map((tournament) => (
            <TournamentRow key={tournament.id} tournament={tournament} />
          ))}
        </tbody>
        </table>
      </section>
    </section>
  );
};

export default TournamentsTable;
