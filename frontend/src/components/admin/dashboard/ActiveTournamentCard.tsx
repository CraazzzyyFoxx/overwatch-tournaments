"use client";

import Link from "next/link";
import { ArrowRight, Calendar, Lock } from "lucide-react";

import { Button } from "@/components/ui/button";
import { CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { formatTournamentStages } from "@/lib/tournament-stages";
import { cn } from "@/lib/utils";
import { SurfaceCard } from "./SurfaceCard";
import type { Tournament } from "@/types/tournament.types";

function formatDate(value?: Date | string | null) {
  if (!value) return "-";
  return new Date(value).toLocaleDateString();
}

function MiniStatCell({ value, label, alert }: { value: number; label: string; alert?: boolean }) {
  return (
    <div className="rounded-xl border border-border/50 bg-background/50 p-3 text-center">
      <div className={cn("text-2xl font-semibold tabular-nums", alert ? "text-destructive" : "text-foreground")}>
        {value}
      </div>
      <div className="mt-1 text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
    </div>
  );
}

interface ActiveTournamentCardProps {
  canRead: boolean;
  tournament: Tournament | null;
  encounterCount: number;
  missingLogs: number;
  logCoveragePercent: number;
  canReadMatches: boolean;
}

export function ActiveTournamentCard({
  canRead,
  tournament,
  encounterCount,
  missingLogs,
  logCoveragePercent,
  canReadMatches,
}: ActiveTournamentCardProps) {
  const completedLogs = encounterCount - missingLogs;

  return (
    <SurfaceCard>
      {!canRead ? (
        <CardContent className="p-5">
          <div className="flex flex-col gap-3 rounded-xl border border-dashed border-border/70 bg-background/45 p-5 text-sm text-muted-foreground">
            <div className="flex items-center gap-2 text-foreground">
              <Lock className="size-4 text-muted-foreground" />
              <span className="font-medium">Tournament data is hidden</span>
            </div>
            <p className="leading-6">This role does not have visibility into tournament records.</p>
          </div>
        </CardContent>
      ) : tournament ? (
        <CardContent className="p-5">
          <div className="flex flex-col gap-4">
            {/* Status indicator + type */}
            <div className="flex items-center gap-3">
              <div className={cn(
                "flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium",
                tournament.is_finished
                  ? "bg-muted text-muted-foreground"
                  : "bg-emerald-500/10 text-emerald-400"
              )}>
                {!tournament.is_finished && <span className="size-1.5 rounded-full bg-emerald-400 animate-pulse" />}
                {tournament.is_finished ? "Finished" : "Active"}
              </div>
              <span className="text-xs text-muted-foreground">
                {tournament.is_league ? "League" : "Tournament"}
              </span>
            </div>

            {/* Name */}
            <h2 className="text-xl font-semibold tracking-tight text-foreground line-clamp-1">
              {tournament.name}
            </h2>

            {/* Date */}
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Calendar className="size-3.5" />
              <span>{formatDate(tournament.start_date)} — {formatDate(tournament.end_date)}</span>
              {(tournament.stages?.length ?? 0) > 0 && (
                <span className="ml-2">{tournament.stages.length} stage{tournament.stages.length === 1 ? "" : "s"}</span>
              )}
            </div>

            {tournament.stages?.length > 0 && (
              <div
                className="truncate text-xs text-muted-foreground"
                title={formatTournamentStages(tournament.stages)}
              >
                {formatTournamentStages(tournament.stages)}
              </div>
            )}

            {/* Mini stat cells */}
            <div className={cn("grid gap-3", canReadMatches ? "grid-cols-3" : "grid-cols-1")}>
              <MiniStatCell value={tournament.stages?.length ?? 0} label="Stages" />
              {canReadMatches && (
                <>
                  <MiniStatCell value={encounterCount} label="Encounters" />
                  <MiniStatCell value={missingLogs} label="Missing logs" alert={missingLogs > 0} />
                </>
              )}
            </div>

            {/* Log coverage progress */}
            {encounterCount > 0 && (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>Log coverage</span>
                  <span className="font-medium text-foreground">
                    {completedLogs} / {encounterCount} ({logCoveragePercent}%)
                  </span>
                </div>
                <Progress value={logCoveragePercent} className="h-1.5" />
              </div>
            )}

            {/* CTAs */}
            <div className="flex flex-wrap gap-2">
              <Button asChild size="sm">
                <Link href={`/admin/tournaments/${tournament.id}`}>
                  Open Workspace
                  <ArrowRight className="size-3.5" />
                </Link>
              </Button>
              <Button asChild variant="outline" size="sm">
                <Link href="/admin/tournaments">All Tournaments</Link>
              </Button>
            </div>
          </div>
        </CardContent>
      ) : (
        <CardContent className="p-5">
          <div className="flex flex-col gap-3">
            <p className="text-sm text-muted-foreground">
              No tournaments are currently active. Create or reopen a tournament to populate the dashboard.
            </p>
            <Button asChild variant="outline" size="sm" className="w-fit">
              <Link href="/admin/tournaments">
                Go to Tournaments
                <ArrowRight className="size-3.5" />
              </Link>
            </Button>
          </div>
        </CardContent>
      )}
    </SurfaceCard>
  );
}
