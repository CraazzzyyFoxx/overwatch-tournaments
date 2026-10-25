"use client";

import { useQuery } from "@tanstack/react-query";

import { tournamentStreamsQueryOptions, tournamentVodsQueryOptions } from "../_queries/tournamentStreams";

/** `undefined` (or a non-id) keeps the read off — how callers gate it on the phase. */
function isTournamentId(tournamentId: number | undefined): tournamentId is number {
  return typeof tournamentId === "number" && Number.isFinite(tournamentId) && tournamentId > 0;
}

export function useTournamentStreamsQuery(tournamentId: number | undefined) {
  return useQuery({
    ...tournamentStreamsQueryOptions(tournamentId ?? -1),
    enabled: isTournamentId(tournamentId),
  });
}

export function useTournamentVodsQuery(tournamentId: number | undefined) {
  return useQuery({
    ...tournamentVodsQueryOptions(tournamentId ?? -1),
    enabled: isTournamentId(tournamentId),
  });
}
