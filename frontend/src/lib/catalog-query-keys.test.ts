import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { heroQueryKeys } from "@/lib/heroes/query-keys";
import { mapQueryKeys } from "@/lib/maps/query-keys";

/**
 * The catalogue editors (`admin/content/heroes|maps`) drop the whole entity with
 * one bare-root invalidation — `["heroes"]`, `["maps"]` — including from the
 * alias-resolution queue, which computes the root from the entity type and so
 * cannot name a longer key. Every catalogue read therefore has to sit UNDER that
 * root: the previous spellings (`heroes-all`, `heroes-select-options`,
 * `maps-all`, `maps-select-options`) did not, which is how an alias edit left
 * every picker in the app showing the old name until a reload.
 */
describe("catalogue keys live under the root their editor invalidates", () => {
  it("drops the hero and map catalogues on a bare-root invalidation", async () => {
    const client = new QueryClient();
    const entries = [
      heroQueryKeys.catalog(),
      mapQueryKeys.catalog(),
      mapQueryKeys.catalog(true),
      mapQueryKeys.lookup()
    ];
    for (const key of entries) client.setQueryData(key, ["stale"]);

    await client.invalidateQueries({ queryKey: heroQueryKeys.all() });
    await client.invalidateQueries({ queryKey: mapQueryKeys.all() });

    const stillFresh = entries.filter((key) => !client.getQueryState(key)?.isInvalidated);
    expect(stillFresh).toEqual([]);
  });

  it("keeps the gamemode payload in its own cache entry", () => {
    expect(mapQueryKeys.catalog(true)).not.toEqual(mapQueryKeys.catalog());
  });
});
