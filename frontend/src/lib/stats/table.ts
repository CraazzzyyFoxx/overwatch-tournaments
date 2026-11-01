import type { CatalogEntityRead } from "@/types/catalog.types";
import type { StatDefinition } from "@/types/discipline.types";
import type { MatchWithStats } from "@/types/encounter.types";
import type { PersonDisplay } from "@/types/user.types";

import { aggregateFacts, selectFacts, type FactGrain, type Observation } from "./facts";

/** One observed member's row: `values` holds only the stats the match actually recorded for them (missing ≠ 0). */
interface StatsTableRow {
  key: string;
  workspaceMemberId: number;
  playerId: number;
  /** How the match's game names the member; `display.canonical` builds the profile link. */
  display: PersonDisplay;
  /** stat code → value at the table's grain; an unobserved stat has no key. */
  values: Record<string, number>;
  /** Series tables: how many of the folded matches observed the member at the table's grain. */
  mapsPlayed?: number;
}

/** One participation (`encounter_team_id`) with its observed members. */
interface StatsTableSection {
  key: string;
  encounterTeamId: number;
  /** The participation's name snapshot. */
  name: string;
  /** Whether the participation is still a live seat of the encounter; `null` when the read did not say. */
  live: boolean | null;
  /** The participation's observed whole-match team facts (`score`, …). */
  teamFacts: Record<string, number>;
  rows: StatsTableRow[];
}

export interface StatsTable {
  /** Only the stats at least one row observed, in declared order. */
  columns: StatDefinition[];
  /** Every participant, in seat order — any number of them. */
  sections: StatsTableSection[];
}

/** Segment 0 (the whole match) first, then the child segments in order. */
export function matchSegments(match: Pick<MatchWithStats, "statistics">): number[] {
  return [0, ...match.statistics.segments.map((segment) => segment.segment).sort((a, b) => a - b)];
}

/** The member-total grain of the whole match: every member, no entity. */
export const MEMBER_TOTALS: FactGrain = { segment: 0, entity: "none" };

/**
 * The entities (characters) that have member facts at `segment` in at least one of the matches, by name. Each is
 * a grain of its own: its rows are never merged with the no-entity totals of the same members.
 */
export function memberEntities(
  matches: readonly Pick<MatchWithStats, "statistics">[],
  segment: number
): CatalogEntityRead[] {
  const named = new Map<number, CatalogEntityRead>();
  const used = new Set<number>();
  for (const { statistics } of matches) {
    for (const entity of statistics.entities) named.set(entity.id, entity);
    for (const fact of statistics.facts) {
      if (fact.segment === segment && fact.workspace_member_id != null && fact.entity_id != null) {
        used.add(fact.entity_id);
      }
    }
  }
  return [...used]
    .map((id) => named.get(id))
    .filter((entity): entity is CatalogEntityRead => entity !== undefined)
    .sort((a, b) => a.name.localeCompare(b.name) || a.id - b.id);
}

/** Whether any member fact exists at any grain: the only honest reason to say a match recorded no statistics. */
export function hasMemberFacts(match: Pick<MatchWithStats, "statistics">): boolean {
  return match.statistics.facts.some((fact) => fact.workspace_member_id != null);
}

const byDeclaredOrder = (a: StatDefinition, b: StatDefinition) =>
  a.sort_order - b.sort_order || a.code.localeCompare(b.code);

/**
 * A declared stat is a column when a row observed it, active or not: history keeps its retired stats, and a
 * declared stat nobody observed is not a column of empty cells.
 */
function columnsOf(
  defs: readonly StatDefinition[],
  sections: readonly StatsTableSection[]
): StatDefinition[] {
  const observed = new Set(
    sections.flatMap((section) => section.rows.flatMap((row) => Object.keys(row.values)))
  );
  return defs.filter((def) => observed.has(def.code)).sort(byDeclaredOrder);
}

const participationOf = (
  match: Pick<MatchWithStats, "encounter">,
  encounterTeamId: number
): boolean | null =>
  match.encounter?.teams ? match.encounter.teams.some((seat) => seat.id === encounterTeamId) : null;

/** The member-totals table lists every observed member (event-only ones included); any other grain only those with values. */
const listsEveryMember = (grain: FactGrain) => grain.segment === 0 && grain.entity === "none";

/**
 * One match as a generic statistics table at one grain: a segment and either the member totals (no entity) or
 * one entity's rows. Every participant is a section; values are the native facts untouched, and a grain's facts
 * are never added to another's (segment 0 with its child segments, null-entity totals with per-entity rows).
 */
export function buildMatchTable(
  match: Pick<MatchWithStats, "participants" | "statistics" | "encounter">,
  defs: readonly StatDefinition[],
  grain: FactGrain
): StatsTable {
  const { members, facts } = match.statistics;
  const selected = selectFacts(facts, grain).filter((fact) => fact.workspace_member_id != null);
  const sections = match.participants.map((participant): StatsTableSection => {
    const rows = members
      .filter((member) => member.encounter_team_id === participant.encounter_team_id)
      .map((member): StatsTableRow => {
        const values: Record<string, number> = {};
        for (const fact of selected) {
          if (
            fact.encounter_team_id === member.encounter_team_id &&
            fact.workspace_member_id === member.workspace_member_id
          ) {
            values[fact.stat_code] = fact.value;
          }
        }
        return {
          key: `${member.encounter_team_id}:${member.workspace_member_id}`,
          workspaceMemberId: member.workspace_member_id,
          playerId: member.player_id,
          display: member.display,
          values
        };
      })
      .filter((row) => listsEveryMember(grain) || Object.keys(row.values).length > 0);
    return {
      key: String(participant.encounter_team_id),
      encounterTeamId: participant.encounter_team_id,
      name: participant.name,
      live: participationOf(match, participant.encounter_team_id),
      teamFacts: participant.team_facts,
      rows
    };
  });
  return { columns: columnsOf(defs, sections), sections };
}

/**
 * A series' generic statistics: every participation and member across the matches, each stat folded across the
 * matches that observed it by its own declared aggregation, over the whole matches (segment 0) at either the
 * member totals or one entity. `last` follows the deterministic `(played_at ?? created_at, match id)` order.
 * Participations are keyed by `encounter_team_id`: a replacement seat is never paired with the participation it
 * replaced.
 */
export function buildSeriesTable(
  matches: readonly Pick<
    MatchWithStats,
    "id" | "participants" | "statistics" | "encounter" | "played_at" | "created_at"
  >[],
  defs: readonly StatDefinition[],
  entity: FactGrain["entity"] = "none"
): StatsTable {
  const defByCode = new Map(defs.map((def) => [def.code, def]));
  const grain: FactGrain = { segment: 0, entity };
  interface Fold {
    row: Omit<StatsTableRow, "values">;
    observations: Map<string, Observation[]>;
    maps: number;
  }
  const sections = new Map<number, { section: StatsTableSection; folds: Map<number, Fold> }>();

  for (const match of matches) {
    const at = match.played_at ?? match.created_at;
    const selected = selectFacts(match.statistics.facts, grain);
    for (const participant of match.participants) {
      let entry = sections.get(participant.encounter_team_id);
      if (!entry) {
        entry = {
          section: {
            key: String(participant.encounter_team_id),
            encounterTeamId: participant.encounter_team_id,
            name: participant.name,
            live: participationOf(match, participant.encounter_team_id),
            teamFacts: {},
            rows: []
          },
          folds: new Map()
        };
        sections.set(participant.encounter_team_id, entry);
      }
      for (const member of match.statistics.members) {
        if (member.encounter_team_id !== participant.encounter_team_id) continue;
        const own = selected.filter(
          (fact) =>
            fact.workspace_member_id === member.workspace_member_id &&
            fact.encounter_team_id === member.encounter_team_id
        );
        // At an entity grain a match counts for the members it has that entity's values for.
        if (entity !== "none" && own.length === 0) continue;
        let fold = entry.folds.get(member.workspace_member_id);
        if (!fold) {
          fold = {
            row: {
              key: `${member.encounter_team_id}:${member.workspace_member_id}`,
              workspaceMemberId: member.workspace_member_id,
              playerId: member.player_id,
              display: member.display
            },
            observations: new Map(),
            maps: 0
          };
          entry.folds.set(member.workspace_member_id, fold);
        }
        fold.maps += 1;
        for (const fact of own) {
          if (!defByCode.has(fact.stat_code)) continue;
          const seen = fold.observations.get(fact.stat_code) ?? [];
          seen.push({ value: fact.value, at, matchId: match.id });
          fold.observations.set(fact.stat_code, seen);
        }
      }
    }
  }

  const folded = [...sections.values()].map(({ section, folds }): StatsTableSection => ({
    ...section,
    rows: [...folds.values()].map(({ row, observations, maps }): StatsTableRow => {
      const values: Record<string, number> = {};
      for (const [code, seen] of observations) {
        const value = aggregateFacts(seen, (defByCode.get(code) as StatDefinition).aggregation);
        if (value != null) values[code] = value;
      }
      return { ...row, values, mapsPlayed: maps };
    })
  }));
  return { columns: columnsOf(defs, folded), sections: folded };
}
