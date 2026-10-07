import { queryOptions } from "@tanstack/react-query";

import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import tournamentService from "@/services/tournament.service";

// `ref` is the raw `/tournaments/{ref}` URL segment -- the current slug, a
// legacy numeric id, or a retired slug -- or, in an admin flow that already
// resolved it, the tournament's own numeric id. Whichever one the caller
// holds, that is what this lookup keys on for its whole lifecycle; every other
// query in the route tree keys on the resolved numeric id.
export function tournamentOverviewQueryOptions(ref: string | number) {
  return queryOptions({
    queryKey: tournamentQueryKeys.detail(ref),
    queryFn: () => tournamentService.getPublicOverview(ref),
    staleTime: 60_000,
  });
}
