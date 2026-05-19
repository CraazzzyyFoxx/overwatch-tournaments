"use client";

import React from "react";
import { useQuery } from "@tanstack/react-query";
import analyticsService from "@/services/analytics.service";
import { AnomalyKind, MatchQuality } from "@/types/analytics.types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface MatchQualityCardProps {
  tournamentId: number;
}

function scoreColor(score: number): string {
  if (score >= 75) return "bg-emerald-500/20 text-emerald-200";
  if (score >= 50) return "bg-amber-400/20 text-amber-100";
  return "bg-red-500/20 text-red-100";
}

function anomalyTone(kind: AnomalyKind): string {
  switch (kind) {
    case "smurf":
      return "border-amber-400/50 text-amber-200";
    case "troll":
      return "border-red-500/50 text-red-200";
    case "throw":
      return "border-purple-500/50 text-purple-200";
    case "sandbag":
      return "border-fuchsia-500/50 text-fuchsia-200";
    default:
      return "";
  }
}

/**
 * Match Quality view (Phase 4) — one row per encounter with the four
 * sub-scores plus anomaly flags. Lives on the analytics page as a collapsible
 * section; expand to reveal flag reasons inline.
 */
export default function MatchQualityCard({ tournamentId }: MatchQualityCardProps) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["analytics-match-quality", tournamentId],
    queryFn: () => analyticsService.getMatchQuality(tournamentId),
    staleTime: 60_000,
  });

  const rows: MatchQuality[] = React.useMemo(() => {
    if (!data) return [];
    return [...data].sort((a, b) => a.encounter_id - b.encounter_id);
  }, [data]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Match quality & anomalies</CardTitle>
        <p className="text-xs text-muted-foreground">
          Post-hoc per-encounter scoring (competitiveness, predictability, skill balance) plus
          IsolationForest / changepoint anomaly flags.
        </p>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-full" />
          </div>
        )}
        {isError && (
          <p className="text-sm text-muted-foreground">
            Match Quality not available. Run the inference pipeline first.
          </p>
        )}
        {rows.length === 0 && !isLoading && !isError && (
          <p className="text-sm text-muted-foreground">No match-quality rows yet.</p>
        )}
        {rows.length > 0 && (
          <ul className="divide-y divide-border/60">
            {rows.map((row) => (
              <li key={row.encounter_id} className="py-2 grid grid-cols-12 gap-3 items-center text-sm">
                <span className="col-span-2 font-medium tabular-nums">
                  Encounter #{row.encounter_id}
                </span>
                <span
                  className={cn(
                    "col-span-1 text-center rounded-md px-2 py-0.5 font-semibold",
                    scoreColor(row.quality_score),
                  )}
                  title="Quality score 0-100"
                >
                  {row.quality_score.toFixed(0)}
                </span>
                <span className="col-span-2 text-center text-xs text-muted-foreground">
                  comp <strong>{row.competitiveness.toFixed(0)}</strong>
                </span>
                <span className="col-span-2 text-center text-xs text-muted-foreground">
                  pred <strong>{row.predictability.toFixed(0)}</strong>
                </span>
                <span className="col-span-2 text-center text-xs text-muted-foreground">
                  skill <strong>{row.skill_balance.toFixed(0)}</strong>
                </span>
                <span className="col-span-3 flex gap-1 flex-wrap justify-end">
                  {(row.anomaly_flags ?? []).map((flag, i) => (
                    <Badge
                      key={`${flag.player_id}-${flag.kind}-${i}`}
                      variant="outline"
                      className={cn("text-[10px] uppercase", anomalyTone(flag.kind))}
                      title={flag.reasons.join("\n")}
                    >
                      {flag.kind} · #{flag.player_id}
                    </Badge>
                  ))}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
