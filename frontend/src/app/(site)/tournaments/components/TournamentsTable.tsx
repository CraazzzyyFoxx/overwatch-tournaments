"use client";

import React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { LayoutGrid, ArrowUpRight } from "lucide-react";

import type { Tournament } from "@/types/tournament.types";
import { cn, formatDateRange } from "@/lib/utils";
import { TOURNAMENT_STATUS_META } from "@/lib/tournament-status";
import { relativeTime, stageProgress } from "./tournaments-helpers";

const stopPropagation = (event: React.MouseEvent) => event.stopPropagation();

const TournamentRow = ({ tournament }: { tournament: Tournament }) => {
  const router = useRouter();
  const designClass =
    tournament.status === "live" || tournament.status === "playoffs"
      ? "live"
      : tournament.status === "registration" || tournament.status === "check_in"
        ? "upcoming"
        : tournament.status === "completed" || tournament.status === "archived"
          ? "finished"
          : "draft";
  const statusMeta = TOURNAMENT_STATUS_META[tournament.status];
  const stage = stageProgress(tournament, tournament.status);
  const players = tournament.participants_count ?? 0;

  return (
    <tr onClick={() => router.push(`/tournaments/${tournament.id}`)}>
      <td>
        <span className="tn-id">#{tournament.number}</span>
      </td>
      <td>
        <div className="tn-name-cell">
          <span className="nm">
            {tournament.name}
            {(tournament.status === "live" || tournament.status === "playoffs") && (
              <span className="status-pill live" style={{ fontSize: "8.5px", padding: "2px 7px" }}>
                <span className="dot" />
                Live
              </span>
            )}
          </span>
          <span className="sub">
            {formatDateRange(tournament.start_date, tournament.end_date)}
            {tournament.is_league && (
              <>
                <span className="sep">·</span>League
              </>
            )}
          </span>
        </div>
      </td>
      <td>
        <span className={`tn-status ${designClass}`}>
          <span className="dot" />
          {statusMeta.badgeLabel}
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
            <span className="big">{players}</span>
            <span className="sub">players</span>
          </div>
        </div>
      </td>
      <td className="r">
        <span className="tn-id">
          {relativeTime(tournament.updated_at ?? tournament.start_date)}
        </span>
      </td>
      <td className="r">
        <div className="tn-actions">
          <Link
            href={`/tournaments/${tournament.id}/bracket`}
            className="icon-btn"
            title="Bracket"
            onClick={stopPropagation}
          >
            <LayoutGrid width={13} height={13} />
          </Link>
          <Link
            href={`/tournaments/${tournament.id}`}
            className="icon-btn"
            title="Open"
            onClick={stopPropagation}
          >
            <ArrowUpRight width={13} height={13} />
          </Link>
        </div>
      </td>
    </tr>
  );
};

interface TournamentsTableProps {
  tournaments: Tournament[];
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}

const TournamentsTable = ({ tournaments, page, pageSize, onPageChange }: TournamentsTableProps) => {
  const total = tournaments.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(page, totalPages);
  const start = (safePage - 1) * pageSize;
  const pageItems = tournaments.slice(start, start + pageSize);
  const rangeStart = total === 0 ? 0 : start + 1;
  const rangeEnd = Math.min(start + pageSize, total);

  return (
    <section className="tn-card">
      <table className="tn">
        <thead>
          <tr>
            <th style={{ width: 60 }}>#</th>
            <th>Tournament</th>
            <th style={{ width: 120 }}>Status</th>
            <th style={{ width: 170 }}>Stage</th>
            <th style={{ width: 110 }}>Players</th>
            <th className="r" style={{ width: 110 }}>
              Updated
            </th>
            <th className="r" style={{ width: 80 }} />
          </tr>
        </thead>
        <tbody>
          {pageItems.map((tournament) => (
            <TournamentRow key={tournament.id} tournament={tournament} />
          ))}
        </tbody>
      </table>

      <div className="pagination">
        <span className="page-info">
          Showing {rangeStart}–{rangeEnd} of {total}
        </span>
        <div className="page-controls">
          <button
            type="button"
            className={cn("page-btn", safePage <= 1 && "disabled")}
            onClick={() => safePage > 1 && onPageChange(safePage - 1)}
            disabled={safePage <= 1}
          >
            ←
          </button>
          {Array.from({ length: totalPages }, (_, index) => index + 1).map((pageNumber) => (
            <button
              key={pageNumber}
              type="button"
              className={cn("page-btn", pageNumber === safePage && "active")}
              onClick={() => onPageChange(pageNumber)}
            >
              {pageNumber}
            </button>
          ))}
          <button
            type="button"
            className={cn("page-btn", safePage >= totalPages && "disabled")}
            onClick={() => safePage < totalPages && onPageChange(safePage + 1)}
            disabled={safePage >= totalPages}
          >
            →
          </button>
        </div>
      </div>
    </section>
  );
};

export default TournamentsTable;
