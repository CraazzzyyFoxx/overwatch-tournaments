"use client";

import { useQuery } from "@tanstack/react-query";

import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import tournamentService from "@/services/tournament.service";

export function useTournamentQuery(tournamentId: number) {
  return useQuery({
    queryKey: tournamentQueryKeys.detail(tournamentId),
    queryFn: () => tournamentService.get(tournamentId),
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
