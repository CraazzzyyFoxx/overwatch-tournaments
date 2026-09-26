import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { mapQueryKeys } from "@/lib/maps/query-keys";
import mapService from "@/services/map.service";
import { MapRead } from "@/types/map.types";
import { PaginatedResponse } from "@/types/pagination.types";

/** Same reasoning as the hero catalogue: reference data, edited a few times a year. */
const CATALOG_STALE_MS = 5 * 60 * 1000;

/** Module-level so the observer's select identity is stable across renders. */
const toResults = (page: PaginatedResponse<MapRead>): MapRead[] => page.results;

/**
 * The whole map catalogue, name-sorted, cached once for the app.
 *
 * `withGamemode` is a second cache entry rather than a flag on one, because it
 * is a different payload: the backend only eager-loads and serializes the
 * gamemode relation when it is asked for, so without it every `gamemode` comes
 * back null. It is not a filtered view of the plain list.
 *
 * Filtering (e.g. dropping off-rotation maps) belongs at the call site — it is a
 * view of this list, not another request.
 */
export function useMapsCatalog({
  enabled = true,
  withGamemode = false
}: { enabled?: boolean; withGamemode?: boolean } = {}): UseQueryResult<MapRead[]> {
  return useQuery({
    queryKey: mapQueryKeys.catalog(withGamemode),
    queryFn: () =>
      mapService.getAll({ perPage: -1, ...(withGamemode ? { entities: ["gamemode"] } : {}) }),
    select: toResults,
    staleTime: CATALOG_STALE_MS,
    enabled
  });
}
