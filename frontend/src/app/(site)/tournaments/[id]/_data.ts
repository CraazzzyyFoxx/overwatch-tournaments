import { cache } from "react";

import tournamentService from "@/services/tournament.service";

export const getTournamentOverview = cache(async (tournamentId: number) => {
  return tournamentService.getPublicOverview(tournamentId);
});
