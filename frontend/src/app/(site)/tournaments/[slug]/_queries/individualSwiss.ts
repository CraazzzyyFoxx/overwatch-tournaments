import { queryOptions } from "@tanstack/react-query";

import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import tournamentService from "@/services/tournament.service";
import type { Tournament } from "@/types/tournament.types";

import { getBracketRefetchInterval } from "../bracket/bracketData";

type TournamentRef = Pick<Tournament, "id" | "status">;

/** The personal table, refetched every 15 s while the tournament is live, like the bracket's standings. */
export function playerStandingsQueryOptions(tournament: TournamentRef) {
  return queryOptions({
    queryKey: tournamentQueryKeys.playerStandings(tournament.id),
    queryFn: () => tournamentService.getPlayerStandings(tournament.id),
    refetchInterval: getBracketRefetchInterval(tournament.status),
    refetchIntervalInBackground: false
  });
}

/** One stage's rounds, on the same cadence. */
export function individualRoundsQueryOptions(tournament: TournamentRef, stageId: number) {
  return queryOptions({
    queryKey: tournamentQueryKeys.individualRounds(tournament.id, stageId),
    queryFn: () => tournamentService.getIndividualRounds(tournament.id, stageId),
    refetchInterval: getBracketRefetchInterval(tournament.status),
    refetchIntervalInBackground: false
  });
}
