import { queryOptions } from "@tanstack/react-query";

import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import heroService from "@/services/hero.service";
import type { Tournament } from "@/types/tournament.types";

/**
 * Hero play-time across the whole tournament — the statistics section's default
 * sub-tab, and therefore its first-paint read.
 */
export function tournamentHeroPlaytimeQueryOptions(
  tournament: Pick<Tournament, "id" | "workspace_id">
) {
  return queryOptions({
    queryKey: tournamentQueryKeys.heroPlaytime(tournament.id),
    queryFn: () =>
      heroService.getHeroPlaytime(1, -1, "all", tournament.id, {
        workspaceId: tournament.workspace_id
      })
  });
}
