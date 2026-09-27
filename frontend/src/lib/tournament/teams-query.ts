import { queryOptions } from "@tanstack/react-query";

import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import teamService from "@/services/team.service";
import type { Tournament } from "@/types/tournament.types";

/**
 * The tournament's materialized teams — the post-balancer `tournament.team`
 * list, rosters included.
 *
 * Shared by the Teams section's client view and by the Teams route's server
 * prefetch: both must produce the SAME key, or the dehydrated entry lands
 * beside the one the client then fetches instead of satisfying it.
 */
export function tournamentTeamsQueryOptions(
  tournament: Pick<Tournament, "id" | "workspace_id">
) {
  return queryOptions({
    queryKey: tournamentQueryKeys.teams(tournament.id, tournament.workspace_id),
    queryFn: () =>
      teamService.getAll({
        tournamentId: tournament.id,
        workspaceId: tournament.workspace_id
      })
  });
}
