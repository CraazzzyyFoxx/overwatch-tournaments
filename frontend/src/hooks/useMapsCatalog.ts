import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { mapsCatalogQueryOptions } from "@/lib/maps/catalog-query";
import { MapRead } from "@/types/map.types";
import { PaginatedResponse } from "@/types/pagination.types";

/** Module-level so the observer's select identity is stable across renders. */
const toResults = (page: PaginatedResponse<MapRead>): MapRead[] => page.results;

/**
 * The whole map catalogue, name-sorted, cached once for the app. The request
 * itself lives in `mapsCatalogQueryOptions`, which the Maps route prefetches on
 * the server; this is the observer plus the unwrap.
 *
 * Filtering (e.g. dropping off-rotation maps) belongs at the call site — it is a
 * view of this list, not another request.
 */
export function useMapsCatalog({
  enabled = true,
  withGamemode = false
}: { enabled?: boolean; withGamemode?: boolean } = {}): UseQueryResult<MapRead[]> {
  return useQuery({
    ...mapsCatalogQueryOptions({ withGamemode }),
    select: toResults,
    enabled
  });
}
