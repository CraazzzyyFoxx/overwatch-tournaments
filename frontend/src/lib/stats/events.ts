import type { CatalogEntityRead } from "@/types/catalog.types";
import type { EventTypeDefinition } from "@/types/discipline.types";
import type { MatchWithStats } from "@/types/encounter.types";
import type { MatchEvents } from "@/types/killfeed.types";

/** One native event, named through the match's own participants and members and the discipline's declared types. */
export interface EventRow {
  id: number;
  segment: number;
  /** Seconds from the start of the segment. */
  t: number;
  /** The declared event type's name, or its code when the discipline's metadata does not list it. */
  type: string;
  actor: EventParty | null;
  target: EventParty | null;
  /** The character(s) the event names; their meaning is the discipline's, never interpreted here. */
  entity: CatalogEntityRead | null;
  relatedEntity: CatalogEntityRead | null;
}

/** Who an event acts or targets: a member's name in the match's game and/or a participation's name; never invented. */
export interface EventParty {
  member: string | null;
  team: string | null;
}

/**
 * The generic reading of a native event timeline: every event of every declared type in the order served
 * (`segment`, `t`, `id`), grouped by nothing and interpreted by nothing. `data` is a discipline's own contract
 * and stays in its module; an actor, target or entity the match cannot resolve stays unresolved.
 */
export function buildEventRows(
  feed: Pick<MatchEvents, "events" | "entities">,
  match: Pick<MatchWithStats, "participants" | "statistics">,
  eventTypes: readonly EventTypeDefinition[]
): EventRow[] {
  const typeName = new Map(eventTypes.map((definition) => [definition.code, definition.name]));
  const memberName = new Map(
    match.statistics.members.map((member) => [member.workspace_member_id, member.display.name])
  );
  const teamName = new Map(
    match.participants.map((participant) => [participant.encounter_team_id, participant.name])
  );
  const entity = new Map(feed.entities.map((row) => [row.id, row]));

  const party = (memberId: number | null, teamId: number | null): EventParty | null => {
    if (memberId == null && teamId == null) return null;
    return {
      member: memberId == null ? null : (memberName.get(memberId) ?? null),
      team: teamId == null ? null : (teamName.get(teamId) ?? null)
    };
  };

  return [...feed.events]
    .sort((a, b) => a.segment - b.segment || a.t - b.t || a.id - b.id)
    .map((event) => ({
      id: event.id,
      segment: event.segment,
      t: event.t,
      type: typeName.get(event.type) ?? event.type,
      actor: party(event.actor_member_id, event.actor_team_id),
      target: party(event.target_member_id, event.target_team_id),
      entity: event.entity_id == null ? null : (entity.get(event.entity_id) ?? null),
      relatedEntity:
        event.related_entity_id == null ? null : (entity.get(event.related_entity_id) ?? null)
    }));
}
