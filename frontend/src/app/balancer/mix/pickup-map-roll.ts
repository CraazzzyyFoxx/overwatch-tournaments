import type { MapRead } from "@/types/map.types";

/**
 * Rolling the next map of a mix, kept pure so the panel stays presentational
 * and the odds are testable.
 *
 * The pool is the competitive catalogue (`in_competitive`): arcade-only maps
 * and modes the workspace never plays a mix on stay out unless a host picks
 * them by hand. Maps this mix has already played are skipped while any fresh
 * one remains, so a night of mixes walks the pool instead of repeating.
 */

/** One mode a host can roll within -- derived from the competitive maps, never the raw gamemode table. */
export type RollableMode = {
  id: number;
  name: string;
  image_path: string;
};

/** The competitive catalogue; `gamemode` is only present when the caller asked for the relation. */
const IN_POOL = (map: MapRead) => map.in_competitive && map.gamemode != null;

/** Every mode with at least one competitive map, name-ordered for a stable chip row. */
export function rollableModes(maps: readonly MapRead[]): RollableMode[] {
  const byId = new Map<number, RollableMode>();
  for (const map of maps.filter(IN_POOL)) {
    if (!byId.has(map.gamemode.id)) {
      byId.set(map.gamemode.id, {
        id: map.gamemode.id,
        name: map.gamemode.name,
        image_path: map.gamemode.image_path,
      });
    }
  }
  return [...byId.values()].sort((a, b) => a.name.localeCompare(b.name));
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
  maps: readonly MapRead[],
  {
    gamemodeId,
    playedMapIds,
    random = Math.random,
  }: {
    gamemodeId: number | null;
    playedMapIds: Iterable<number>;
    random?: () => number;
  },
): MapRead | null {
  let pool = maps.filter(IN_POOL);
  if (gamemodeId != null) {
    pool = pool.filter((map) => map.gamemode_id === gamemodeId);
  }
  if (pool.length === 0) return null;

  const played = new Set(playedMapIds);
  const fresh = pool.filter((map) => !played.has(map.id));
  if (fresh.length > 0) pool = fresh;

  if (gamemodeId != null) return pickOne(pool, random);

  const byMode = new Map<number, MapRead[]>();
  for (const map of pool) {
    const bucket = byMode.get(map.gamemode_id);
    if (bucket) bucket.push(map);
    else byMode.set(map.gamemode_id, [map]);
  }
  // Modes in catalogue order, so the same `random` value lands on the same
  // mode regardless of how the maps were sorted upstream.
  const modes = [...byMode.keys()].sort((a, b) => a - b);
  return pickOne(byMode.get(pickOne(modes, random)) ?? [], random);
}
