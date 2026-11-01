import { describe, expect, it } from "vitest";

import { catalogEntity } from "@/test/catalog";
import type { EventTypeDefinition } from "@/types/discipline.types";
import type { MatchWithStats } from "@/types/encounter.types";
import type { MatchEvent } from "@/types/killfeed.types";

import { buildEventRows } from "./events";

const match = {
  participants: [
    { encounter_team_id: 1, name: "Alpha" },
    { encounter_team_id: 2, name: "Bravo" },
    { encounter_team_id: 3, name: "Charlie" }
  ],
  statistics: {
    members: [
      { encounter_team_id: 1, workspace_member_id: 10, display: { name: "Ann", tag: "#1", canonical: null, snapshot: null } },
      { encounter_team_id: 3, workspace_member_id: 30, display: { name: "Cy", tag: "#3", canonical: null, snapshot: null } }
    ]
  }
} as unknown as Pick<MatchWithStats, "participants" | "statistics">;

const TYPES = [{ id: 1, code: "kill", name: "Kill", active: true }] as EventTypeDefinition[];
const ASHE = catalogEntity({ id: 500, name: "Ashe" });

const event = (overrides: Partial<MatchEvent>): MatchEvent => ({
  id: 1,
  segment: 0,
  t: 1,
  type: "kill",
  actor_member_id: null,
  actor_team_id: null,
  target_member_id: null,
  target_team_id: null,
  entity_id: null,
  related_entity_id: null,
  data: null,
  ...overrides
});

describe("buildEventRows", () => {
  it("names a three-participant timeline through members, participations and declared types, in served order", () => {
    const rows = buildEventRows(
      {
        entities: [ASHE],
        events: [
          event({
            id: 3,
            segment: 1,
            t: 2,
            type: "ultimate_start",
            actor_member_id: 30,
            actor_team_id: 3
          }),
          event({
            id: 2,
            t: 9,
            actor_member_id: 10,
            actor_team_id: 1,
            target_team_id: 2,
            entity_id: 500
          }),
          event({ id: 1, t: 9, actor_team_id: 3, related_entity_id: 500 })
        ]
      },
      match,
      TYPES
    );
    expect(rows.map((row) => row.id)).toEqual([1, 2, 3]);
    expect(rows[1]).toMatchObject({
      type: "Kill",
      actor: { member: "Ann", team: "Alpha" },
      target: { member: null, team: "Bravo" },
      entity: ASHE
    });
    expect(rows[0].actor).toEqual({ member: null, team: "Charlie" });
    expect(rows[0].relatedEntity).toBe(ASHE);
    // A type the metadata does not list reads as its code; nothing is interpreted from `data`.
    expect(rows[2]).toMatchObject({
      type: "ultimate_start",
      segment: 1,
      actor: { member: "Cy", team: "Charlie" }
    });
  });

  it("leaves unresolved members, teams and entities unresolved", () => {
    const [row] = buildEventRows(
      { entities: [], events: [event({ actor_member_id: 99, actor_team_id: 98, entity_id: 97 })] },
      match,
      TYPES
    );
    expect(row.actor).toEqual({ member: null, team: null });
    expect(row.entity).toBeNull();
    expect(buildEventRows({ entities: [], events: [event({})] }, match, TYPES)[0].actor).toBeNull();
  });
});
