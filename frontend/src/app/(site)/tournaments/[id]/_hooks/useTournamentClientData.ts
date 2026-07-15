"use client";

import { useQuery } from "@tanstack/react-query";

import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import tournamentService from "@/services/tournament.service";
import { tournamentOverviewQueryOptions } from "../_queries/tournamentOverview";

export { tournamentOverviewQueryOptions };

export function useTournamentQuery(tournamentId: number) {
  return useQuery({
    ...tournamentOverviewQueryOptions(tournamentId),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0,
  });
}

export function useTournamentStagesQuery(tournamentId: number) {
  return useQuery({
    queryKey: tournamentQueryKeys.stages(tournamentId),
    queryFn: () => tournamentService.getStages(tournamentId),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0,
  });
}
