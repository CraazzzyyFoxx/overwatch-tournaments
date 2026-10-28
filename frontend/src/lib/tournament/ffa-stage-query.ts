import { queryOptions } from "@tanstack/react-query";

import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import ffaService from "@/services/ffa.service";

/** One FFA stage's lobbies: the public tabs' read and the layout seed's, so the two keys cannot drift apart. */
export function ffaStageQueryOptions(tournamentId: number, stageId: number) {
  return queryOptions({
    queryKey: tournamentQueryKeys.ffaStage(tournamentId, stageId),
    queryFn: () => ffaService.getStage(tournamentId, stageId)
  });
}
