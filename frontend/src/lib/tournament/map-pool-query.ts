import { queryOptions } from "@tanstack/react-query";

import pickBanService from "@/services/pickBan.service";
import tournamentService from "@/services/tournament.service";

/**
 * The public map-pool reads. Their own `"public"` prefix, not
 * `tournamentQueryKeys.stages`: the organizer-facing stage list is fetched with
 * admin entities and a different lifetime, and sharing one entry would let an
 * admin screen decide what the public pool renders.
 */
export const mapPoolQueryKeys = {
  configs: (tournamentId: number) =>
    ["public", "tournament", tournamentId, "pick-ban-configs"] as const,
  stages: (tournamentId: number) => ["public", "tournament", tournamentId, "stages"] as const
};

/**
 * The tournament's veto configurations — there is no "map pool" entity, the
 * pool is whatever these can produce.
 *
 * No `.catch(() => ({ configs: [] }))`: a failed read must stay
 * distinguishable from "the organizer configured nothing".
 */
export function mapPoolConfigsQueryOptions(tournamentId: number) {
  return queryOptions({
    queryKey: mapPoolQueryKeys.configs(tournamentId),
    queryFn: () => pickBanService.listPublicConfigs(tournamentId)
  });
}

/** The stages a config's `stage_id`/`round` is named against. */
export function mapPoolStagesQueryOptions(tournamentId: number) {
  return queryOptions({
    queryKey: mapPoolQueryKeys.stages(tournamentId),
    queryFn: () => tournamentService.getStages(tournamentId)
  });
}
