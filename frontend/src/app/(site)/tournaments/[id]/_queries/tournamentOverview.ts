import { queryOptions } from "@tanstack/react-query";

import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import tournamentService from "@/services/tournament.service";

export function tournamentOverviewQueryOptions(tournamentId: number) {
  return queryOptions({
    queryKey: tournamentQueryKeys.detail(tournamentId),
    queryFn: () => tournamentService.getPublicOverview(tournamentId),
    staleTime: 60_000,
  });
}
