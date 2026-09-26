import { queryOptions } from "@tanstack/react-query";

import { mapQueryKeys } from "@/lib/maps/query-keys";
import mapService from "@/services/map.service";

/** Same reasoning as the hero catalogue: reference data, edited a few times a year. */
const CATALOG_STALE_MS = 5 * 60 * 1000;

/**
 * The whole map catalogue, cached once for the app.
 *
 * `withGamemode` is a second cache entry rather than a flag on one, because it
 * is a different payload: the backend only eager-loads and serializes the
 * gamemode relation when it is asked for, so without it every `gamemode` comes
 * back null. It is not a filtered view of the plain list.
 *
 * Extracted from `useMapsCatalog` so the Maps route can prefetch it on the
 * server under the same key the hook then reads.
 */
export function mapsCatalogQueryOptions({ withGamemode = false } = {}) {
  return queryOptions({
    queryKey: mapQueryKeys.catalog(withGamemode),
    queryFn: () =>
      mapService.getAll({ perPage: -1, ...(withGamemode ? { entities: ["gamemode"] } : {}) }),
    staleTime: CATALOG_STALE_MS
  });
}
