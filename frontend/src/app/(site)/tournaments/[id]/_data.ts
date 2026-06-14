import { cache } from "react";

import tournamentService from "@/services/tournament.service";

export const getTournament = cache(async (tournamentId: number) => {
  return tournamentService.get(tournamentId);
});

export const getTournamentStages = cache(async (tournamentId: number) => {
  return tournamentService.getStages(tournamentId);
});
