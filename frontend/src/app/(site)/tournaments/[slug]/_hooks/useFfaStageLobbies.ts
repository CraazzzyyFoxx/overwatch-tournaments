"use client";

import { useQueries, type UseQueryResult } from "@tanstack/react-query";

import { FFA_STAGE_TYPES } from "@/lib/bracket/projection";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import ffaService from "@/services/ffa.service";
import type { FfaLobby } from "@/types/ffa.types";
import type { Tournament } from "@/types/tournament.types";

const EMPTY: FfaLobby[] = [];

// Module-level so its identity is stable: `useQueries` re-runs `combine` only
// when the results change.
function combineLobbies(results: UseQueryResult<FfaLobby[]>[]) {
  return {
    lobbies: results.length === 0 ? EMPTY : results.flatMap((result) => result.data ?? []),
    isPending: results.some((result) => result.isPending),
    isError: results.some((result) => result.isError),
    isFetching: results.some((result) => result.isFetching),
    refetch: () => Promise.all(results.map((result) => result.refetch()))
  };
}

/**
 * Every lobby of every FFA stage, in stage order. The encounter list answers
 * duels only, so this is how the public tabs learn a lobby exists. Same key and
 * fetcher as the bracket's `FfaStagePanel`, so the tabs share its cache entries
 * and the realtime `["ffa", id]` invalidation.
 */
export function useFfaStageLobbies(tournament: Tournament | undefined, enabled = true) {
  const stages = (tournament?.stages ?? []).filter((stage) =>
    FFA_STAGE_TYPES.includes(stage.stage_type)
  );
  return useQueries({
    queries: stages.map((stage) => ({
      queryKey: tournamentQueryKeys.ffaStage(tournament!.id, stage.id),
      queryFn: () => ffaService.getStage(tournament!.id, stage.id),
      enabled
    })),
    combine: combineLobbies
  });
}
