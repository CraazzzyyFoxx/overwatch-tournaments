"use client";

import React from "react";
import { useQuery } from "@tanstack/react-query";
import analyticsService from "@/services/analytics.service";
import { StandingsDistribution, TeamAnalytics } from "@/types/analytics.types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";

interface StandingsDistributionCardProps {
  tournamentId: number;
  algorithmId?: number;
  teams: TeamAnalytics[];
}

function MiniHistogram({ histogram }: { histogram: Record<string, number> }) {
  const entries = Object.entries(histogram).map(([pos, count]) => ({
    pos: parseInt(pos, 10),
    count,
  }));
  if (entries.length === 0) return null;
  entries.sort((a, b) => a.pos - b.pos);
  const max = entries.reduce((acc, e) => Math.max(acc, e.count), 0) || 1;

  return (
    <div className="flex items-end gap-[2px] h-6" aria-hidden="true">
      {entries.map((e) => (
        <span
          key={e.pos}
          className="w-1.5 bg-primary/60 rounded-sm"
          style={{ height: `${Math.max(2, (e.count / max) * 100)}%` }}
          title={`pos ${e.pos}: ${e.count}`}
        />
      ))}
    </div>
  );
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(0)}%`;
}

/**
 * Standings Distribution widget (Phase 3) — renders the Monte Carlo simulation
 * output: per-team mean position with p10/p90 band, prob_top1/3/8 columns and
 * a tiny histogram of the 5000-iteration position distribution.
 */
export default function StandingsDistributionCard({
  tournamentId,
  algorithmId,
  teams,
}: StandingsDistributionCardProps) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["analytics-standings-distribution", tournamentId, algorithmId],
    queryFn: () => analyticsService.getStandingsDistribution(tournamentId, algorithmId),
    staleTime: 60_000,
  });

  const teamNamesById = React.useMemo(() => {
    const map: Record<number, string> = {};
    teams.forEach((t) => {
      map[t.id] = t.name;
    });
    return map;
  }, [teams]);

  const rows: StandingsDistribution[] = React.useMemo(() => {
    if (!data) return [];
    return [...data].sort((a, b) => a.mean_position - b.mean_position);
  }, [data]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Predicted standings distribution</CardTitle>
        <p className="text-xs text-muted-foreground">
          Monte Carlo simulation (5000 iter) over the calibrated pairwise win-probability model.
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
            Standings v2 not available. Run the trainer first.
          </p>
        )}
        {data && data.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No predictions yet for this tournament.
          </p>
        )}
        {rows.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Team</TableHead>
                <TableHead className="text-center">Mean (p10–p90)</TableHead>
                <TableHead className="text-center">P(top 1)</TableHead>
                <TableHead className="text-center">P(top 3)</TableHead>
                <TableHead className="text-center">P(top 8)</TableHead>
                <TableHead className="text-center">Distribution</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.team_id}>
                  <TableCell className="font-medium">
                    {teamNamesById[r.team_id] ?? `#${r.team_id}`}
                  </TableCell>
                  <TableCell className="text-center tabular-nums">
                    {r.mean_position.toFixed(1)}{" "}
                    <span className="text-muted-foreground">
                      ({r.p10_position.toFixed(0)}–{r.p90_position.toFixed(0)})
                    </span>
                  </TableCell>
                  <TableCell className="text-center tabular-nums">
                    {formatPercent(r.prob_top1)}
                  </TableCell>
                  <TableCell className="text-center tabular-nums">
                    {formatPercent(r.prob_top3)}
                  </TableCell>
                  <TableCell className="text-center tabular-nums">
                    {formatPercent(r.prob_top8)}
                  </TableCell>
                  <TableCell className="text-center">
                    <MiniHistogram histogram={r.position_histogram} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
