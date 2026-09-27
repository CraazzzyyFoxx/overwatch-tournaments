import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { heroQueryKeys } from "@/lib/heroes/query-keys";
import heroService from "@/services/hero.service";
import { Hero } from "@/types/hero.types";
import { PaginatedResponse } from "@/types/pagination.types";

/**
 * The hero catalogue is reference data: ~45 rows that change when an organizer
 * edits an alias, a few times a year. Five minutes of staleness costs nothing
 * and saves a request on every pregame room, registration form and compare page
 * mount.
 */
const CATALOG_STALE_MS = 5 * 60 * 1000;

/** Module-level so the observer's select identity is stable across renders. */
const toResults = (page: PaginatedResponse<Hero>): Hero[] => page.results;

/**
 * The whole hero catalogue, name-sorted, cached once for the app.
 *
 * `heroService.getAll` already defaults to `sort: "name", order: "asc"`, so
 * every caller that asked for "all heroes" was issuing the same request — under
 * three different keys (`heroes-all`, `heroes-select-options`,
 * `["heroes", "all"]`), which is three copies of the same list in the cache and
 * three refetches for one catalogue edit. A caller that needs another order
 * sorts the returned array; it is not another request.
 */
export function useHeroesCatalog({ enabled = true }: { enabled?: boolean } = {}): UseQueryResult<
  Hero[]
> {
  return useQuery({
    queryKey: heroQueryKeys.catalog(),
    queryFn: () => heroService.getAll({ perPage: -1 }),
    select: toResults,
    staleTime: CATALOG_STALE_MS,
    enabled
  });
}
