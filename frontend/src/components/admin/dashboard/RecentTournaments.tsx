"use client";

import Link from "next/link";
import { ArrowRight, Layers3, Lock } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatTournamentStages } from "@/lib/tournament-stages";
import { SurfaceCard } from "./SurfaceCard";
import type { Tournament } from "@/types/tournament.types";

interface RecentTournamentsProps {
  canRead: boolean;
  tournaments: Tournament[];
}

export function RecentTournaments({ canRead, tournaments }: RecentTournamentsProps) {
  return (
    <SurfaceCard className="flex-1 flex flex-col">
      <CardHeader className="p-5 pb-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="text-sm font-semibold">Recent Tournaments</CardTitle>
            <CardDescription className="mt-1 text-xs">Latest events</CardDescription>
          </div>
          {canRead && (
            <Button asChild variant="ghost" size="sm" className="-mt-1 shrink-0 text-muted-foreground">
              <Link href="/admin/tournaments">
                View all
                <ArrowRight className="size-3.5" />
              </Link>
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="px-5 pb-5 flex-1 flex flex-col">
        {canRead ? (
          tournaments.length > 0 ? (
            <div className="divide-y divide-border/50 rounded-xl border border-border/50 overflow-hidden flex-1 flex flex-col">
              {tournaments.slice(0, 6).map((t) => (
                <Link
                  key={t.id}
                  href={`/admin/tournaments/${t.id}`}
                  className="flex items-center justify-between gap-3 px-3 py-2.5 bg-background/40 transition-colors hover:bg-accent/30"
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-foreground">{t.name}</div>
                    <div
                      className="mt-0.5 truncate text-xs text-muted-foreground"
                      title={formatTournamentStages(t.stages ?? []) || "No stages"}
                    >
                      {formatTournamentStages(t.stages ?? []) || "No stages"}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="flex items-center gap-1 text-xs text-muted-foreground">
                      <Layers3 className="size-3" />
                      {t.stages?.length ?? 0}
                    </span>
                    <Badge variant={t.is_finished ? "outline" : "default"} className="text-xs">
                      {t.is_finished ? "Finished" : "Active"}
                    </Badge>
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No tournaments available.</p>
          )
        ) : (
          <div className="flex flex-col gap-3 rounded-xl border border-dashed border-border/70 bg-background/45 p-5 text-sm text-muted-foreground">
            <div className="flex items-center gap-2 text-foreground">
              <Lock className="size-4 text-muted-foreground" />
              <span className="font-medium">Tournament queue is hidden</span>
            </div>
            <p className="leading-6">Tournament records are not visible from the dashboard for this role.</p>
          </div>
        )}
      </CardContent>
    </SurfaceCard>
  );
}
