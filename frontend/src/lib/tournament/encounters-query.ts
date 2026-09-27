import { queryOptions } from "@tanstack/react-query";

import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import encounterService from "@/services/encounter.service";
import type { Tournament } from "@/types/tournament.types";

/**
 * Every encounter of the tournament, with the maps of each series.
 *
 * Deliberately NOT the bracket's cache entry
 * (`tournamentQueryKeys.encounters(id, workspaceId)`): the bracket asks for no
 * `matches` entity, and a shared key would let whichever screen mounted first
 * decide whether the row expansion has any maps to show. The `"maps"` marker in
 * the key keeps the two payloads apart; the shared prefix keeps realtime
 * invalidation (`tournament.encounters`) reaching both.
 *
 * Three consumers share it: the Matches section, the statistics section (which
 * counts played maps out of the same entry instead of fetching every encounter
 * a second time), and the Matches route's server prefetch — which must build
 * the key from this one factory or the dehydrated entry misses the client.
 */
export function tournamentEncountersQueryOptions(
  tournament: Pick<Tournament, "id" | "workspace_id">
) {
  return queryOptions({
    queryKey: [
      ...tournamentQueryKeys.encounters(tournament.id, tournament.workspace_id),
      "maps"
    ] as const,
    queryFn: () =>
      encounterService.getAll(
        1,
        "",
        tournament.id,
        -1,
        undefined,
        undefined,
        tournament.workspace_id,
        {
          entities: [
            "tournament",
            "stage",
            "stage_item",
            "home_team",
            "away_team",
            // The row expansion is the series' maps with score, length and
            // mode; the nested relations only serialise when named.
            "matches",
            "matches.map",
            "matches.map.gamemode"
          ]
        }
      )
  });
}
