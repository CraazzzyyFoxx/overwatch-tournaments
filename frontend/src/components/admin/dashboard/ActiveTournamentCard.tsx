"use client";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { ArrowRight, Calendar } from "lucide-react";
import { useFormatter } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardTitle } from "@/components/ui/card";
import { StatusPill } from "@/components/kit/StatusPill";
import { formatTournamentStages } from "@/lib/tournament/stages";
import type { DateFormatter } from "@/components/kit/format-time";
import { PermissionHiddenNotice } from "./PermissionHiddenNotice";
import { tournamentStatus } from "./tournament-status";
import type { Tournament } from "@/types/tournament.types";

function formatDate(format: DateFormatter, value?: Date | string | null) {
  if (!value) return "-";
  return format.dateTime(new Date(value), { dateStyle: "medium" });
}

interface ActiveTournamentCardProps {
  canRead: boolean;
  tournament: Tournament | null;
}

/**
 * The active tournament, as a header: what it is, when, and the one way in.
 *
 * It used to carry a log-coverage bar and a "View all tournaments" button as
 * well — the KPI strip above already states log coverage, and Recent
 * tournaments beside it already links the list, so both said something the
 * screen was already saying.
 */
export function ActiveTournamentCard({ canRead, tournament }: Readonly<ActiveTournamentCardProps>) {
  const format = useFormatter();
  if (!canRead) {
    return (
      <Card>
        <CardContent className="pt-6">
          <PermissionHiddenNotice title="Tournament data is hidden" permission="tournament read" />
        </CardContent>
      </Card>
    );
  }

  if (!tournament) {
    return (
      <Card>
        <CardContent className="flex flex-col gap-3 pt-6">
          <p className="text-sm text-muted-foreground">
            No tournaments are currently active. Create or reopen a tournament to populate the
            dashboard.
          </p>
          <Button asChild variant="outline" size="sm" className="w-fit">
            <HoverPrefetchLink href="/admin/tournaments">
              View all tournaments
              <ArrowRight className="size-3.5" aria-hidden />
            </HoverPrefetchLink>
          </Button>
        </CardContent>
      </Card>
    );
  }

  const status = tournamentStatus(tournament.is_finished);
  const stageCount = tournament.stages?.length ?? 0;
  const stageList = stageCount > 0 ? formatTournamentStages(tournament.stages) : null;

  return (
    <Card>
      <CardContent className="flex flex-wrap items-start justify-between gap-4 pt-6">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <StatusPill tone={status.tone} dot={!tournament.is_finished}>
              {status.label}
            </StatusPill>
            {tournament.is_league ? "League" : "Tournament"}
          </div>

          <CardTitle asChild className="mt-2 line-clamp-1 text-xl text-foreground">
            <h2>{tournament.name}</h2>
          </CardTitle>

          {/* Dates, stage count and stage names on one line — the only place
              the stage count is stated. */}
          <p className="mt-1 flex min-w-0 flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
            <Calendar className="size-3.5 shrink-0" aria-hidden />
            <span className="tabular-nums">
              {formatDate(format, tournament.start_date)} — {formatDate(format, tournament.end_date)}
            </span>
            {stageCount > 0 && (
              <>
                <span aria-hidden>·</span>
                <span className="tabular-nums">
                  {stageCount} stage{stageCount === 1 ? "" : "s"}
                </span>
              </>
            )}
            {stageList && (
              <>
                <span aria-hidden>·</span>
                <span className="truncate" title={stageList}>
                  {stageList}
                </span>
              </>
            )}
          </p>
        </div>

        <Button asChild size="sm" className="shrink-0">
          <HoverPrefetchLink href={`/admin/tournaments/${tournament.id}`}>
            Open tournament
            <ArrowRight className="size-3.5" aria-hidden />
          </HoverPrefetchLink>
        </Button>
      </CardContent>
    </Card>
  );
}
