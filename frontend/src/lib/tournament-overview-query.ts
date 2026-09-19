import { queryOptions } from "@tanstack/react-query";

import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import tournamentService from "@/services/tournament.service";

// `slug` is the raw `/tournaments/{slug}` URL segment: the current slug, a
// legacy numeric id, or a retired slug -- whichever one the viewer's URL
// carries. The resolved tournament's OWN numeric id (once loaded) is what
// every other query in this route tree keys on; only this overview lookup
// keys by the URL segment itself.
export function tournamentOverviewQueryOptions(slug: string) {
  return queryOptions({
    queryKey: tournamentQueryKeys.detail(slug),
    queryFn: () => tournamentService.getPublicOverview(slug),
    staleTime: 60_000,
  });
}
