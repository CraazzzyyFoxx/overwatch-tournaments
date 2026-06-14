"use client";

import React from "react";
import { Tournament } from "@/types/tournament.types";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Calendar, Users, ExternalLink } from "lucide-react";
import { cn, formatDateRange } from "@/lib/utils";
import { getTournamentStatusMeta } from "@/lib/tournament-status";

export const TournamentChallongeLink = ({
  tournament,
  stages,
}: {
  tournament: Tournament;
  stages?: Tournament["stages"];
}) => {
  const tournamentStages = stages ?? tournament.stages ?? [];
  const slug =
    tournament.challonge_slug ??
    tournamentStages
      .slice()
      .sort((a, b) => a.order - b.order)
      .find((stage) => stage.challonge_slug)?.challonge_slug;

  if (!slug) {
    return null;
  }

  return (
    <Link
      className="flex items-center gap-1 text-xs text-white/55 hover:text-white/80 transition-colors"
      href={`https://challonge.com/${slug}`}
      target="_blank"
      rel="noopener noreferrer"
    >
      <ExternalLink className="w-3 h-3" />
      <span>Bracket</span>
    </Link>
  );
};

export const TournamentChallongeLinkInline = ({
  tournament,
  stages,
}: {
  tournament: Tournament;
  stages?: Tournament["stages"];
}) => {
  const tournamentStages = stages ?? tournament.stages ?? [];
  const slug =
    tournament.challonge_slug ??
    tournamentStages
      .slice()
      .sort((a, b) => a.order - b.order)
      .find((stage) => stage.challonge_slug)?.challonge_slug;

  if (!slug) {
    return null;
  }

  return (
    <Link
      className="text-sm text-blue-500 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 transition-colors font-medium"
      href={`https://challonge.com/${slug}`}
      target="_blank"
      rel="noopener noreferrer"
    >
      View Bracket
    </Link>
  );
};

const TournamentCard = ({ tournament }: { tournament: Tournament }) => {
  const router = useRouter();
  const statusMeta = getTournamentStatusMeta(tournament.status);

  const onClick = (event: React.MouseEvent) => {
    const isLinkClicked = (event.target as HTMLElement).closest("a");
    if (isLinkClicked) return;
    router.push(`/tournaments/${tournament.id}`);
  };

  return (
    <div
      className={cn(
        "group flex flex-col rounded-xl border border-white/[0.07] bg-white/[0.02] p-5 cursor-pointer",
        "transition-colors duration-200 hover:bg-white/[0.045] hover:border-white/[0.13]",
      )}
      onClick={onClick}
    >
      {/* Tags row */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {tournament.is_league && (
            <span className="inline-flex items-center text-[10px] font-semibold px-2 py-0.5 rounded-full bg-purple-500/15 text-purple-400 border border-purple-500/20 tracking-wide uppercase">
              League
            </span>
          )}
          <span
            className={cn(
              "inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide",
              statusMeta.badgeClassName
            )}
          >
            {statusMeta.dotClassName ? (
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  statusMeta.dotClassName,
                  tournament.status === "live" && "animate-pulse"
                )}
              />
            ) : null}
            {statusMeta.badgeLabel}
          </span>
        </div>
        {!tournament.is_league && (
          <span className="text-xs tabular-nums text-white/45">#{tournament.number}</span>
        )}
      </div>

      {/* Title */}
      <h3 className="text-sm font-semibold text-white leading-snug mb-3 line-clamp-2">
        {tournament.name}
      </h3>

      {/* Meta */}
      <div className="space-y-1.5 flex-1 mb-4">
        <div className="flex items-center gap-2 text-xs text-white/60">
          <Calendar className="w-3.5 h-3.5 shrink-0 text-white/40" />
          <span>{formatDateRange(tournament.start_date, tournament.end_date)}</span>
        </div>
        <div className="flex items-center gap-2 text-xs text-white/60">
          <Users className="w-3.5 h-3.5 shrink-0 text-white/40" />
          <span>{tournament.participants_count} participants</span>
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-end pt-3 border-t border-white/[0.06]">
        <div onClick={(e) => e.stopPropagation()}>
          <TournamentChallongeLink tournament={tournament} />
        </div>
      </div>
    </div>
  );
};

export default TournamentCard;
