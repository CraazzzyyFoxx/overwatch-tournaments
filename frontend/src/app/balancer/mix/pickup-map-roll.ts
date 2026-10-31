import type { CatalogEntityRead } from "@/types/catalog.types";

/**
 * Rolling the next map of a mix, kept pure so the panel stays presentational
 * and the odds are testable.
 *
 * The pool is the competitive catalogue: a map is in it unless `attrs.in_competitive` says `false`
 * (a game that declares no such flag has only competitive maps), so arcade-only maps the workspace never
 * plays a mix on stay out unless a host picks them by hand. A game without modes (League) rolls its maps
 * directly; a map's mode, when it has one, is its `parent`. Maps this mix has already played are skipped while any fresh
 * one remains, so a night of mixes walks the pool instead of repeating.
 */

/** One mode a host can roll within -- derived from the competitive maps, never the raw gamemode table. */
export type RollableMode = {
  id: number;
  name: string;
  image_path: string | null;
};

/** The competitive catalogue: absent `in_competitive` means competitive. */
const IN_POOL = (map: CatalogEntityRead) => map.attrs.in_competitive !== false;

/** Every mode with at least one competitive map, name-ordered for a stable chip row. */
export function rollableModes(maps: readonly CatalogEntityRead[]): RollableMode[] {
  const byId = new Map<number, RollableMode>();
  for (const { parent } of maps.filter(IN_POOL)) {
    // A map without a mode adds no chip: there is nothing to roll within.
    if (parent && !byId.has(parent.id)) {
      byId.set(parent.id, { id: parent.id, name: parent.name, image_path: parent.image_path });
    }
  }
  return [...byId.values()].sort((a, b) => a.name.localeCompare(b.name));
}

/** More than one competitive map: a game with one (or none) has nothing to roll, pick or announce. */
export function hasMapChoice(maps: readonly CatalogEntityRead[]): boolean {
  return maps.filter(IN_POOL).length > 1;
}

function pickOne<T>(items: readonly T[], random: () => number): T {
  return items[Math.min(items.length - 1, Math.floor(random() * items.length))];
}

/**
 * Roll the next map.
 *
 * `gamemodeId` restricts the roll to one mode; `null` rolls the **mode first**
 * (uniform across modes) and then a map inside it, so a two-map mode comes up
 * as often as a seven-map one -- players ask "what are we playing?", not
 * "which of the 30 maps". Maps in `playedMapIds` are skipped while anything
 * unplayed is left in the chosen scope; once the scope is exhausted the whole
 * scope is fair game again. `null` when nothing qualifies.
 */
export function rollNextMap(
  maps: readonly CatalogEntityRead[],
  {
    gamemodeId,
    playedMapIds,
    random = Math.random,
  }: {
    gamemodeId: number | null;
    playedMapIds: Iterable<number>;
    random?: () => number;
  },
): CatalogEntityRead | null {
  let pool = maps.filter(IN_POOL);
  if (gamemodeId != null) {
    pool = pool.filter((map) => map.parent_id === gamemodeId);
  }
  if (pool.length === 0) return null;

  const played = new Set(playedMapIds);
  const fresh = pool.filter((map) => !played.has(map.id));
  if (fresh.length > 0) pool = fresh;

  if (gamemodeId != null) return pickOne(pool, random);

  // Maps without a mode share one bucket (`null`), so a mode-less game is a single bucket and rolls its maps directly.
  const byMode = new Map<number | null, CatalogEntityRead[]>();
  for (const map of pool) {
    const bucket = byMode.get(map.parent_id);
    if (bucket) bucket.push(map);
    else byMode.set(map.parent_id, [map]);
  }
  // Modes in catalogue order, so the same `random` value lands on the same
  // mode regardless of how the maps were sorted upstream.
  const modes = [...byMode.keys()].sort((a, b) => (a ?? -1) - (b ?? -1));
  return pickOne(byMode.get(pickOne(modes, random)) ?? [], random);
}
