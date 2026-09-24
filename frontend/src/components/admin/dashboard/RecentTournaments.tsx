"use client";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { ArrowRight, Layers3 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusPill } from "@/components/kit/StatusPill";
import { formatTournamentStages } from "@/lib/tournament/stages";
import { PermissionHiddenNotice } from "./PermissionHiddenNotice";
import { tournamentStatus } from "./tournament-status";
import type { Tournament } from "@/types/tournament.types";

interface RecentTournamentsProps {
  canRead: boolean;
  tournaments: Tournament[];
}

export function RecentTournaments({ canRead, tournaments }: Readonly<RecentTournamentsProps>) {
  return (
    <Card className="flex flex-1 flex-col">
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <CardTitle asChild>
            <h2>Recent tournaments</h2>
          </CardTitle>
          {canRead && (
            <Button
              asChild
              variant="ghost"
              size="sm"
              className="-mt-1.5 shrink-0 text-muted-foreground"
            >
              <HoverPrefetchLink href="/admin/tournaments">
                View all tournaments
                <ArrowRight className="size-3.5" aria-hidden />
              </HoverPrefetchLink>
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col">
        {!canRead ? (
          <PermissionHiddenNotice title="Tournament queue is hidden" permission="tournament read" />
        ) : tournaments.length > 0 ? (
          <ul className="divide-y divide-border/50">
            {tournaments.slice(0, 6).map((t) => {
              const stageCount = t.stages?.length ?? 0;
              const stageList = formatTournamentStages(t.stages ?? []) || "No stages yet";
              const status = tournamentStatus(t.is_finished);

              return (
                <li key={t.id}>
                  {/* Bleeds to the card edge so the hover fill spans the card. */}
                  <HoverPrefetchLink
                    href={`/admin/tournaments/${t.id}`}
                    className="-mx-6 flex items-center justify-between gap-3 px-6 py-2.5 transition-colors hover:bg-accent/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-foreground">{t.name}</div>
                      <div
                        className="mt-0.5 truncate text-xs text-muted-foreground"
                        title={stageList}
                      >
                        {stageList}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <span className="flex items-center gap-1 text-xs tabular-nums text-muted-foreground">
                        <Layers3 className="size-3" aria-hidden />
                        {stageCount}
                        <span className="sr-only"> stages</span>
                      </span>
                      <StatusPill tone={status.tone}>{status.label}</StatusPill>
                    </div>
                  </HoverPrefetchLink>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">
            No tournaments yet. Create one to start tracking stages, teams and logs here.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
