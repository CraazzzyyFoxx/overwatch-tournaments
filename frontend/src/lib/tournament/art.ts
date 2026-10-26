import type { CatalogEntityRead } from "@/types/catalog.types";
import type { Encounter } from "@/types/encounter.types";
import type { Tournament } from "@/types/tournament.types";

/**
 * Modes whose stills are no tournament's picture: an empty custom-game room,
 * the practice range, and the payload-race maps, whose art has the map's name
 * printed across it.
 */
const SKIPPED_MODES = new Set(["workshop", "practice-range", "payload-race"]);

/**
 * The map last played in a series: its highest position, else, for logs never
 * bound to a position, the match stored last. Only a map with a still counts.
 */
function lastPlayedMap({ matches }: Pick<Encounter, "matches">): string | null {
  return (
    matches
      .filter((match) => match.map?.image_path)
      .sort((left, right) => (left.map_index ?? -1) - (right.map_index ?? -1) || left.id - right.id)
      .at(-1)?.map?.image_path ?? null
  );
}

/**
 * A tournament's picture: the organizer's cover; else the map last played in
 * it, read from `latest`, its latest series with parsed logs
 * (`encounterService.getLatestPlayed`); else, before anything is played, a
 * still of one of its game's maps (`catalog`) fixed by its id.
 *
 * `undefined` while a read it needs is still out, so a card waits rather than
 * swap one picture for another; `null` when there is no picture at all.
 */
export function tournamentPicture(
  tournament: Pick<Tournament, "id" | "cover_image_url">,
  latest: Pick<Encounter, "matches"> | null | undefined,
  catalog: readonly CatalogEntityRead[] | undefined
): string | null | undefined {
  if (tournament.cover_image_url) return tournament.cover_image_url;
  if (latest === undefined) return undefined;
  const played = latest && lastPlayedMap(latest);
  if (played) return played;
  if (catalog === undefined) return undefined;

  // In id order whatever order the read returned: the home page reads the
  // catalog on the server and the tournament list in the browser, and both
  // must land a tournament on one map.
  const maps = catalog
    .filter((map) => map.image_path && !SKIPPED_MODES.has(map.parent?.slug ?? ""))
    .sort((left, right) => left.id - right.id);
  if (maps.length === 0) return null;
  // Fibonacci hashing, read from the top bits: consecutive ids (a community's
  // weekly cups) scatter across the list. The low bits modulo the list's
  // length would hand neighbouring ids the same or the next map.
  const index = Math.floor(((Math.imul(tournament.id, 0x9e3779b1) >>> 0) / 0x1_0000_0000) * maps.length);
  return maps[index]?.image_path ?? null;
}
