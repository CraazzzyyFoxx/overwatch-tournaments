import type { CatalogEntityRead } from "@/types/catalog.types";
import type { PersonDisplay } from "@/types/user.types";
import type { MatchWithStats } from "@/types/encounter.types";

/**
 * A character counts as played in a segment past this much time on it. The module's long-standing rule: the
 * hero strips and the leaders' portraits never list a one-second swap.
 */
export const HERO_PLAYED_SECONDS = 60;

/** Time on one character in one segment. */
export interface HeroTime {
  entity: CatalogEntityRead;
  seconds: number;
}

/** One observed member as the Overwatch match views read them: segment-keyed values, no entity grain. */
export interface OwPlayer {
  workspace_member_id: number;
  /** The global player the member is. */
  user_id: number;
  /** How the match's game names the member; `display.canonical` builds the profile link. */
  display: PersonDisplay;
  /** segment (0 = whole match) → stat code → value, from the member's no-entity facts. */
  stats: Record<number, Record<string, number>>;
  /** segment → the characters the member played longer than `HERO_PLAYED_SECONDS` in it. */
  heroes: Record<number, CatalogEntityRead[]>;
  /** segment → every character the member was observed on, longest first (swaps of any length included). */
  heroTimes: Record<number, HeroTime[]>;
}

/** One participant of a duel with its observed members. `id` is the `encounter_team_id`. */
export interface OwTeam {
  id: number;
  slot: number;
  /** The source tournament team; null for a mix/scrim seat or once the source team is deleted. */
  team_id: number | null;
  /** The participation's name snapshot. */
  name: string;
  /** The source team's name and logo, when the read expanded the encounter's seats. */
  team: { name: string; image_url: string | null } | null;
  /** Whether the participation is still one of the encounter's live seats; `null` when the read did not say. */
  live: boolean | null;
  players: OwPlayer[];
}

export interface OwMatchView {
  home: OwTeam;
  away: OwTeam;
}

/**
 * The two-sided view of a native match for the Overwatch scoreboards: the participant in the lower seat is
 * `home`, the other `away`. Only a duel has one — any other number of participants is the generic table's.
 * Values are the match's native facts re-keyed, never recomputed.
 */
export function owMatchView(match: MatchWithStats): OwMatchView | null {
  if (match.participants.length !== 2) return null;
  const [home, away] = [...match.participants].sort((a, b) => a.slot - b.slot);

  const { members, facts, entities } = match.statistics;
  const entityById = new Map(entities.map((entity) => [entity.id, entity]));
  const players = new Map<string, OwPlayer>();
  const teams = new Map<number, OwPlayer[]>();
  for (const member of members) {
    const player: OwPlayer = {
      workspace_member_id: member.workspace_member_id,
      user_id: member.player_id,
      display: member.display,
      stats: {},
      heroes: {},
      heroTimes: {}
    };
    players.set(`${member.encounter_team_id}:${member.workspace_member_id}`, player);
    teams.set(member.encounter_team_id, [...(teams.get(member.encounter_team_id) ?? []), player]);
  }

  for (const fact of facts) {
    if (fact.workspace_member_id == null) continue;
    const player = players.get(`${fact.encounter_team_id}:${fact.workspace_member_id}`);
    if (!player) continue;
    if (fact.entity_id == null) {
      (player.stats[fact.segment] ??= {})[fact.stat_code] = fact.value;
    } else if (fact.stat_code === "hero_time_played" && fact.value > 0) {
      const entity = entityById.get(fact.entity_id);
      if (!entity) continue;
      (player.heroTimes[fact.segment] ??= []).push({ entity, seconds: fact.value });
      if (fact.value > HERO_PLAYED_SECONDS) (player.heroes[fact.segment] ??= []).push(entity);
    }
  }
  for (const player of players.values()) {
    for (const times of Object.values(player.heroTimes)) times.sort((a, b) => b.seconds - a.seconds);
  }

  const seats = match.encounter?.teams;
  const team = (participant: typeof home): OwTeam => {
    const seat = seats?.find((candidate) => candidate.id === participant.encounter_team_id);
    return {
      id: participant.encounter_team_id,
      slot: participant.slot,
      team_id: participant.tournament_team_id,
      name: participant.name,
      team: seat?.team ? { name: seat.team.name, image_url: seat.team.image_url } : null,
      live: seats ? seat !== undefined : null,
      players: teams.get(participant.encounter_team_id) ?? []
    };
  };
  return { home: team(home), away: team(away) };
}

/**
 * The characters a player (the global `userId`) played longer than `HERO_PLAYED_SECONDS` in any segment of the
 * match, each once, in the order the facts are served (segment, then character).
 */
export function playedCharacters(
  match: MatchWithStats,
  userId: number | null
): CatalogEntityRead[] {
  if (userId == null) return [];
  const { members, facts, entities } = match.statistics;
  const seats = new Set(
    members
      .filter((member) => member.player_id === userId)
      .map((member) => `${member.encounter_team_id}:${member.workspace_member_id}`)
  );
  const entityById = new Map(entities.map((entity) => [entity.id, entity]));
  const played = new Map<number, CatalogEntityRead>();
  for (const fact of facts) {
    if (
      fact.entity_id == null ||
      fact.stat_code !== "hero_time_played" ||
      fact.value <= HERO_PLAYED_SECONDS
    )
      continue;
    if (
      fact.workspace_member_id == null ||
      !seats.has(`${fact.encounter_team_id}:${fact.workspace_member_id}`)
    )
      continue;
    const entity = entityById.get(fact.entity_id);
    if (entity && !played.has(entity.id)) played.set(entity.id, entity);
  }
  return [...played.values()];
}
