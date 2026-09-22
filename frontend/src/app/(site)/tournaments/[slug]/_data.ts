import { cache } from "react";

import { isNotFoundError } from "@/lib/api/error";
import tournamentService from "@/services/tournament.service";
import type { Tournament } from "@/types/tournament.types";

export type TournamentOverviewState =
  { kind: "success"; overview: Tournament } | { kind: "not-found" } | { kind: "error" };

async function loadTournamentOverviewState(ref: string): Promise<TournamentOverviewState> {
  if (!ref) {
    return { kind: "not-found" };
  }

  try {
    const overview = await tournamentService.getPublicOverview(ref);
    return { kind: "success", overview };
  } catch (error) {
    return isNotFoundError(error) ? { kind: "not-found" } : { kind: "error" };
  }
}

// `ref` is the raw `/tournaments/{ref}` URL segment: the current slug, a
// legacy numeric id, or a retired slug. The backend resolves all three to the
// same tournament (see resolve_public_ref) -- no client-side format
// validation is meaningful anymore, so a bad ref simply 404s upstream.
export const getTournamentOverviewState = cache(async (ref: string) => {
  return loadTournamentOverviewState(ref);
});
