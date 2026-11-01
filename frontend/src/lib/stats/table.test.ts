import { describe, expect, it } from "vitest";

import { catalogEntity } from "@/test/catalog";
import type { StatDefinition } from "@/types/discipline.types";
import type { MatchWithStats, NativeFact } from "@/types/encounter.types";

import {
  MEMBER_TOTALS,
  buildMatchTable,
  buildSeriesTable,
  hasMemberFacts,
  matchSegments,
  memberEntities
} from "./table";

const def = (
  code: string,
  aggregation: string,
  sort_order: number,
  active = true
): StatDefinition =>
  ({
    id: sort_order,
    code,
    name: code,
    value_format: "integer",
    aggregation,
    group: null,
    active,
    sort_order
  }) as StatDefinition;

const DEFS = [
  def("kills", "sum", 2),
  def("score", "sum", 1),
  def("rank", "last", 3),
  def("retired", "sum", 4, false),
  def("unseen", "sum", 5)
];

const fact = (
  team: number,
  member: number | null,
  segment: number,
  stat_code: string,
  value: number,
  entity_id: number | null = null
): NativeFact => ({
  encounter_team_id: team,
  workspace_member_id: member,
  entity_id,
  segment,
  stat_code,
  value
});

const ASHE = catalogEntity({ id: 500, name: "Ashe" });
const BRAND = catalogEntity({ id: 501, name: "Brand" });

/** Three participants (a lobby), one with no source team and one event-only member. */
function lobby(overrides: Partial<MatchWithStats> = {}): MatchWithStats {
  const participant = (id: number, slot: number, source: number | null) => ({
    encounter_team_id: id,
    slot,
    source_position: 3 - slot,
    tournament_team_id: source,
    name: `T${id}`,
    result: null,
    team_facts: id === 3 ? {} : { score: id }
  });
  const member = (team: number, id: number, player: number, handle: string) => {
    const at = handle.lastIndexOf("#");
    return {
      encounter_team_id: team,
      workspace_member_id: id,
      player_id: player,
      display: { name: handle.slice(0, at), tag: handle.slice(at), canonical: `Canonical ${player}`, snapshot: null },
      handle_snapshot: handle,
      observed_role: null
    };
  };
  return {
    id: 5,
    created_at: "2026-01-01T00:00:00Z",
    played_at: null,
    encounter: null,
    participants: [participant(1, 1, 11), participant(2, 2, 12), participant(3, 3, null)],
    statistics: {
      members: [
        member(1, 10, 1, "Ann#1"),
        member(2, 20, 2, "Bob#2"),
        member(3, 30, 3, "Cy#3"),
        member(3, 31, 4, "Event only#4")
      ],
      segments: [
        { segment: 2, kind: "round", attrs: {} },
        { segment: 1, kind: "round", attrs: {} }
      ],
      facts: [
        fact(1, 10, 0, "kills", 7),
        fact(1, 10, 0, "kills", 99, ASHE.id), // per-character row: never added to the member total
        fact(1, 10, 0, "kills", 5, BRAND.id),
        fact(2, 20, 0, "kills", 8, ASHE.id),
        fact(1, 10, 1, "kills", 3),
        fact(1, null, 0, "score", 1), // a team fact is not a member row
        fact(2, 20, 0, "kills", 0), // zero is a value
        fact(3, 30, 0, "retired", 4)
      ],
      entities: [BRAND, ASHE]
    },
    ...overrides
  } as unknown as MatchWithStats;
}

describe("buildMatchTable", () => {
  it("lists every participant and member (event-only included) with exactly the member-grain whole-match facts", () => {
    const table = buildMatchTable(lobby(), DEFS, MEMBER_TOTALS);
    expect(
      table.sections.map((section) => [section.name, section.rows.map((row) => row.display.name)])
    ).toEqual([
      ["T1", ["Ann"]],
      ["T2", ["Bob"]],
      ["T3", ["Cy", "Event only"]]
    ]);
    expect(table.sections[0].rows[0].values).toEqual({ kills: 7 });
    expect(table.sections[1].rows[0].values).toEqual({ kills: 0 });
    expect(table.sections[2].rows[1].values).toEqual({});
    expect(table.sections[2].encounterTeamId).toBe(3);
    expect(table.sections[0].teamFacts).toEqual({ score: 1 });
  });

  it("carries the canonical player name apart from the observed handle", () => {
    const row = buildMatchTable(lobby(), DEFS, MEMBER_TOTALS).sections[0].rows[0];
    expect([row.display.name, row.display.canonical, row.playerId]).toEqual(["Ann", "Canonical 1", 1]);
  });

  it("columns are the declared stats someone observed, in declared order, retired ones included", () => {
    expect(
      buildMatchTable(lobby(), DEFS, MEMBER_TOTALS).columns.map((column) => column.code)
    ).toEqual(["kills", "retired"]);
  });

  it("a child segment lists only the members it has values for, and segments are ordered", () => {
    const match = lobby();
    expect(matchSegments(match)).toEqual([0, 1, 2]);
    const table = buildMatchTable(match, DEFS, { segment: 1, entity: "none" });
    expect(table.sections.map((section) => section.rows.map((row) => row.values))).toEqual([
      [{ kills: 3 }],
      [],
      []
    ]);
  });

  it("an entity grain is its own table: that character's rows, never merged with the member totals", () => {
    const match = lobby();
    const ashe = buildMatchTable(match, DEFS, { segment: 0, entity: ASHE.id });
    expect(
      ashe.sections.map((section) => section.rows.map((row) => [row.display.name, row.values]))
    ).toEqual([[["Ann", { kills: 99 }]], [["Bob", { kills: 8 }]], []]);
    const brand = buildMatchTable(match, DEFS, { segment: 0, entity: BRAND.id });
    expect(brand.sections[0].rows[0].values).toEqual({ kills: 5 });
    // The totals still read 7 and 0: neither character's rows were added.
    expect(buildMatchTable(match, DEFS, MEMBER_TOTALS).sections[0].rows[0].values).toEqual({
      kills: 7
    });
  });

  it("when the only member facts are entity-grain, the totals table has no columns yet the match has statistics", () => {
    const match = lobby();
    match.statistics.facts = [fact(1, 10, 0, "kills", 9, ASHE.id)];
    expect(hasMemberFacts(match)).toBe(true);
    expect(buildMatchTable(match, DEFS, MEMBER_TOTALS).columns).toEqual([]);
    expect(
      buildMatchTable(match, DEFS, { segment: 0, entity: ASHE.id }).columns.map((c) => c.code)
    ).toEqual(["kills"]);
  });

  it("a match with only team facts has no member statistics", () => {
    const match = lobby();
    match.statistics.facts = [fact(1, null, 0, "score", 1)];
    expect(hasMemberFacts(match)).toBe(false);
  });
});

describe("memberEntities", () => {
  it("offers the characters that have member facts in the segment, by name", () => {
    expect(memberEntities([lobby()], 0).map((entity) => entity.name)).toEqual(["Ashe", "Brand"]);
    expect(memberEntities([lobby()], 1)).toEqual([]);
  });

  it("ignores team facts and entities no fact names", () => {
    const match = lobby();
    match.statistics.facts = [fact(1, null, 0, "score", 1, ASHE.id)];
    expect(memberEntities([match], 0)).toEqual([]);
  });
});

describe("buildSeriesTable", () => {
  const at = (
    id: number,
    played_at: string | null,
    created_at: string,
    kills: number,
    rank: number
  ) =>
    ({
      ...lobby(),
      id,
      played_at,
      created_at,
      statistics: {
        ...lobby().statistics,
        facts: [fact(1, 10, 0, "kills", kills), fact(1, 10, 0, "rank", rank)]
      }
    }) as MatchWithStats;

  it("folds each stat by its own aggregation; `last` follows played_at ?? created_at, then id", () => {
    const table = buildSeriesTable(
      [
        at(2, null, "2026-03-01T00:00:00Z", 4, 2), // upload time is the fallback
        at(1, "2026-02-01T00:00:00Z", "2026-05-01T00:00:00Z", 6, 9),
        at(3, "2026-03-01T00:00:00Z", "2026-03-01T00:00:00Z", 1, 5) // same instant as #2: the higher id is later
      ],
      DEFS
    );
    const ann = table.sections[0].rows[0];
    expect(ann.values).toEqual({ kills: 11, rank: 5 });
    expect(ann.mapsPlayed).toBe(3);
    expect(table.columns.map((column) => column.code)).toEqual(["kills", "rank"]);
  });

  it("keeps participations apart by encounter_team_id and members that observed nothing as rows", () => {
    const table = buildSeriesTable([at(1, null, "2026-01-01T00:00:00Z", 1, 1)], DEFS);
    expect(table.sections.map((section) => section.encounterTeamId)).toEqual([1, 2, 3]);
    expect(table.sections[2].rows.map((row) => [row.display.name, row.values])).toEqual([
      ["Cy", {}],
      ["Event only", {}]
    ]);
    expect(table.sections[0].rows[0].display.canonical).toBe("Canonical 1");
  });

  it("folds one character's rows across the maps without the totals, counting only maps that have them", () => {
    const withAshe = (id: number, kills: number, totalKills: number) =>
      ({
        ...lobby(),
        id,
        statistics: {
          ...lobby().statistics,
          facts: [fact(1, 10, 0, "kills", totalKills), fact(1, 10, 0, "kills", kills, ASHE.id)]
        }
      }) as MatchWithStats;
    const noAshe = {
      ...withAshe(3, 0, 50),
      statistics: { ...lobby().statistics, facts: [fact(1, 10, 0, "kills", 50)] }
    };
    const matches = [withAshe(1, 4, 40), withAshe(2, 6, 60), noAshe as MatchWithStats];
    const ashe = buildSeriesTable(matches, DEFS, ASHE.id).sections[0].rows;
    expect(ashe.map((row) => [row.display.name, row.values, row.mapsPlayed])).toEqual([
      ["Ann", { kills: 10 }, 2]
    ]);
    expect(buildSeriesTable(matches, DEFS).sections[0].rows[0].values).toEqual({ kills: 150 });
  });
});
