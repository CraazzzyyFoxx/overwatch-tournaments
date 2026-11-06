import { queryOptions } from "@tanstack/react-query";

import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import flowService from "@/services/flow.service";
import type { Tournament } from "@/types/tournament.types";

import { getBracketRefetchInterval } from "../bracket/bracketData";

/** The public flow graph with its results, refetched every 15 s while the tournament is live, like the bracket. */
export function flowQueryOptions(tournament: Pick<Tournament, "id" | "status">) {
  return queryOptions({
    queryKey: tournamentQueryKeys.flow(tournament.id),
    queryFn: () => flowService.get(tournament.id),
    refetchInterval: getBracketRefetchInterval(tournament.status),
    refetchIntervalInBackground: false
  });
}
