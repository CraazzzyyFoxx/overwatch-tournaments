import { cache } from "react";

import { isNotFoundError } from "@/lib/api-error";
import tournamentService from "@/services/tournament.service";
import type { Tournament } from "@/types/tournament.types";

export type TournamentOverviewState =
  { kind: "success"; overview: Tournament } | { kind: "not-found" } | { kind: "error" };

async function loadTournamentOverviewState(tournamentId: number): Promise<TournamentOverviewState> {
  if (!Number.isSafeInteger(tournamentId) || tournamentId <= 0) {
    return { kind: "not-found" };
  }

  try {
    const overview = await tournamentService.getPublicOverview(tournamentId);
    return { kind: "success", overview };
  } catch (error) {
    return isNotFoundError(error) ? { kind: "not-found" } : { kind: "error" };
  }
}

export const getTournamentOverviewState = cache(async (tournamentId: number) => {
  return loadTournamentOverviewState(tournamentId);
});
