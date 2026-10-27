import { mapWithModeName } from "@/lib/catalog/mode";
import type { Encounter } from "@/types/encounter.types";
import type { Tournament } from "@/types/tournament.types";

export interface LiveTournamentGroup {
  tournament: Tournament;
  encounters: Encounter[];
  // Headline encounter rendered in the "NOW" strip.
  current: Encounter;
}

// Group the overview's flat list of live encounters by tournament, preserving
// first-seen order so the most relevant tournament becomes the big card.
export function groupLiveByTournament(live: ReadonlyArray<Encounter>): LiveTournamentGroup[] {
  const order: number[] = [];
  const groups = new Map<number, LiveTournamentGroup>();

  for (const encounter of live) {
    const tournament = encounter.tournament;
    const key = encounter.tournament_id ?? tournament?.id;
    if (key == null || !tournament) continue;

    const existing = groups.get(key);
    if (existing) {
      existing.encounters.push(encounter);
    } else {
      groups.set(key, { tournament, encounters: [encounter], current: encounter });
      order.push(key);
    }
  }

  return order.map((key) => groups.get(key) as LiveTournamentGroup);
}

// Current-map name from the live encounter, if a map is in progress.
export function currentMapName(encounter: Encounter): string | null {
  const index = encounter.current_map_index;
  if (index == null) return null;
  const match = encounter.matches?.[index];
  return mapWithModeName(match?.map, match?.mode);
}
