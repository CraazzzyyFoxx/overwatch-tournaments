"use client";

import { queryOptions, useQuery } from "@tanstack/react-query";

import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import tournamentService from "@/services/tournament.service";

export function tournamentOverviewQueryOptions(tournamentId: number) {
  return queryOptions({
    queryKey: tournamentQueryKeys.detail(tournamentId),
    queryFn: () => tournamentService.getPublicOverview(tournamentId),
    staleTime: 60_000,
  });
}

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
