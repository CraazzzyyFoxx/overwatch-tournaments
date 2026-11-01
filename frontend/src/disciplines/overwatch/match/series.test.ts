import { describe, expect, it } from "vitest";

import type { CatalogEntityRead } from "@/types/catalog.types";
import type { Encounter, MatchWithStats, NativeFact } from "@/types/encounter.types";
import { LogStatsName } from "../stat-names";

import { aggregateSeriesStats } from "./series";
import { teamTotal } from "./stats";

// ─── aggregateSeriesStats ───────────────────────────────────────────────────

interface PlayerSpec {
  id: number;
  stats: Record<string, number>;
  heroIds: number[];
}
interface TeamSpec {
  id: number;
  name: string;
  players: PlayerSpec[];
}

const player = (
  id: number,
  stats: Partial<Record<LogStatsName, number>>,
  heroIds: number[]
): PlayerSpec => ({
  id,
  stats: stats as Record<string, number>,
  heroIds
});
const team = (id: number, name: string, players: PlayerSpec[]): TeamSpec => ({ id, name, players });

const character = (id: number): CatalogEntityRead => ({
  id,
  discipline: "overwatch",
  kind: "character",
  slug: `hero-${id}`,
  name: `Hero ${id}`,
  image_path: null,
  parent_id: null,
  parent: null,
  attrs: {},
  active: true,
  aliases: [],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: null
});

/** A duel observed by the two participations; `slot` follows the participation id, whatever order they are listed in. */
function statMatch(
  id: number,
  home: TeamSpec,
  away: TeamSpec,
  liveSeats: number[] | null = [1, 2]
): MatchWithStats {
  const facts: NativeFact[] = [];
  const entities = new Map<number, CatalogEntityRead>();
  const members = [home, away].flatMap((side) =>
    side.players.map((p) => {
      for (const [code, value] of Object.entries(p.stats)) {
        facts.push({
          encounter_team_id: side.id,
          workspace_member_id: p.id,
          entity_id: null,
          segment: 0,
          stat_code: code,
          value
        });
      }
      for (const heroId of p.heroIds) {
        entities.set(heroId, character(heroId));
        facts.push({
          encounter_team_id: side.id,
          workspace_member_id: p.id,
          entity_id: heroId,
          segment: 0,
          stat_code: "hero_time_played",
          value: 120
        });
      }
      return {
        encounter_team_id: side.id,
        workspace_member_id: p.id,
        player_id: p.id,
        display: { name: `P${p.id}`, tag: "#1", canonical: null, snapshot: null },
        handle_snapshot: `P${p.id}#1`,
        observed_role: null
      };
    })
  );
  return {
    id,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: null,
    played_at: null,
    workspace_id: 1,
    discipline: "overwatch",
    encounter_id: 10,
    encounter_game_id: null,
    map_index: id,
    map_id: id,
    map: null,
    encounter: liveSeats
      ? ({ teams: liveSeats.map((seat) => ({ id: seat })) } as unknown as Encounter)
      : null,
    duration_s: 600,
    log_name: null,
    raw_status: null,
    raw_available: false,
    participants: [home, away].map((side, index) => ({
      encounter_team_id: side.id,
      slot: side.id % 100 === 1 ? 1 : side.id % 100 === 2 ? 2 : side.id,
      source_position: index,
      tournament_team_id: null,
      name: side.name,
      result: null,
      team_facts: {}
    })),
    statistics: { members, segments: [], facts, entities: [...entities.values()] }
  };
}

describe("aggregateSeriesStats", () => {
  it("sums additive stats across maps and counts maps played per player", () => {
    const mapOne = statMatch(
      1,
      team(1, "A", [
        player(11, { [LogStatsName.Eliminations]: 10, [LogStatsName.Deaths]: 2 }, [100])
      ]),
      team(2, "B", [player(21, { [LogStatsName.Eliminations]: 4 }, [200])])
    );
    const mapTwo = statMatch(
      2,
      team(1, "A", [
        player(11, { [LogStatsName.Eliminations]: 6, [LogStatsName.Deaths]: 3 }, [101])
      ]),
      team(2, "B", [player(21, { [LogStatsName.Eliminations]: 5 }, [200])])
    );

    const result = aggregateSeriesStats([mapOne, mapTwo]);
    expect(result).not.toBeNull();
    const row = result!.participations[0].players[0].stats[0];
    expect(row[LogStatsName.Eliminations]).toBe(16);
    expect(row[LogStatsName.Deaths]).toBe(5);
    expect(result!.participations[0].meta[11].mapsPlayed).toBe(2);
    expect(result!.mapsCounted).toBe(2);
    expect(result!.round).toBe(0);
  });

  it("unions heroes across maps without duplicating a repeated pick", () => {
    const result = aggregateSeriesStats([
      statMatch(
        1,
        team(1, "A", [player(11, {}, [100, 101])]),
        team(2, "B", [player(21, {}, [200])])
      ),
      statMatch(
        2,
        team(1, "A", [player(11, {}, [101, 102])]),
        team(2, "B", [player(21, {}, [200])])
      )
    ]);
    const heroes = result!.participations[0].players[0].heroes[0] as { id: number }[];
    expect(heroes.map((hero) => hero.id).sort()).toEqual([100, 101, 102]);
  });

  it("recomputes ratio stats from summed components rather than averaging maps", () => {
    // Map 1: 10 elims / 2 deaths (kd 5). Map 2: 0 elims / 8 deaths (kd 0).
    // Averaging per-map kd gives 2.5; the series truth is 10/10 = 1.
    const result = aggregateSeriesStats([
      statMatch(
        1,
        team(1, "A", [
          player(
            11,
            {
              [LogStatsName.Eliminations]: 10,
              [LogStatsName.Deaths]: 2,
              [LogStatsName.Assists]: 4,
              [LogStatsName.KD]: 5
            },
            [100]
          )
        ]),
        team(2, "B", [player(21, {}, [200])])
      ),
      statMatch(
        2,
        team(1, "A", [
          player(
            11,
            {
              [LogStatsName.Eliminations]: 0,
              [LogStatsName.Deaths]: 8,
              [LogStatsName.Assists]: 2,
              [LogStatsName.KD]: 0
            },
            [100]
          )
        ]),
        team(2, "B", [player(21, {}, [200])])
      )
    ]);
    const row = result!.participations[0].players[0].stats[0];
    expect(row[LogStatsName.KD]).toBe(1);
    expect(row[LogStatsName.KDA]).toBeCloseTo(1.6, 5);
  });

  it("keeps the best single-map multikill instead of summing it", () => {
    const result = aggregateSeriesStats([
      statMatch(
        1,
        team(1, "A", [player(11, { [LogStatsName.MultikillBest]: 4 }, [100])]),
        team(2, "B", [player(21, {}, [200])])
      ),
      statMatch(
        2,
        team(1, "A", [player(11, { [LogStatsName.MultikillBest]: 3 }, [100])]),
        team(2, "B", [player(21, {}, [200])])
      )
    ]);
    expect(result!.participations[0].players[0].stats[0][LogStatsName.MultikillBest]).toBe(4);
  });

  it("derives accuracy from shot counts and omits it when nothing was fired", () => {
    const result = aggregateSeriesStats([
      statMatch(
        1,
        team(1, "A", [
          player(
            11,
            {
              [LogStatsName.ShotsFired]: 100,
              [LogStatsName.ShotsHit]: 40,
              [LogStatsName.CriticalHits]: 10
            },
            [100]
          ),
          player(12, { [LogStatsName.Eliminations]: 3 }, [110])
        ]),
        team(2, "B", [player(21, {}, [200])])
      ),
      statMatch(
        2,
        team(1, "A", [
          player(11, { [LogStatsName.ShotsFired]: 100, [LogStatsName.ShotsHit]: 20 }, [100]),
          player(12, { [LogStatsName.Eliminations]: 2 }, [110])
        ]),
        team(2, "B", [player(21, {}, [200])])
      )
    ]);
    const shooter = result!.participations[0].players.find(
      (entry) => entry.workspace_member_id === 11
    )!.stats[0];
    const abstainer = result!.participations[0].players.find(
      (entry) => entry.workspace_member_id === 12
    )!.stats[0];
    expect(shooter[LogStatsName.WeaponAccuracy]).toBeCloseTo(0.3, 5);
    expect(shooter[LogStatsName.CriticalHitAccuracy]).toBeCloseTo(10 / 60, 5);
    expect(abstainer[LogStatsName.WeaponAccuracy]).toBeUndefined();
  });

  it("drops model-only stats no series value can be derived for", () => {
    const result = aggregateSeriesStats([
      statMatch(
        1,
        team(1, "A", [
          player(11, { [LogStatsName.ImpactPoints]: 42, [LogStatsName.ImpactRank]: 1 }, [100])
        ]),
        team(2, "B", [player(21, {}, [200])])
      )
    ]);
    const row = result!.participations[0].players[0].stats[0];
    expect(row[LogStatsName.ImpactPoints]).toBeUndefined();
    expect(row[LogStatsName.ImpactRank]).toBeUndefined();
  });

  it("ranks series MVPs across both rosters by the playtime-weighted mean of map impact points", () => {
    const stat = (points: number, seconds: number) => ({
      [LogStatsName.ImpactPoints]: points,
      [LogStatsName.HeroTimePlayed]: seconds
    });
    // 11: (1.0·600 − 1.0·400) / 1000 = 0.2 (an unweighted mean would be 0); 12 and 21 both average 0.5.
    const mapOne = statMatch(
      1,
      team(1, "A", [player(11, stat(1, 600), [100]), player(12, stat(0.5, 600), [110])]),
      team(2, "B", [player(21, stat(0.5, 600), [200]), player(22, { [LogStatsName.Eliminations]: 9 }, [210])])
    );
    const mapTwo = statMatch(
      2,
      team(1, "A", [player(11, stat(-1, 400), [100]), player(12, stat(0.5, 100), [110])]),
      team(2, "B", [player(21, stat(0.5, 600), [200]), player(22, { [LogStatsName.Eliminations]: 9 }, [210])])
    );
    const result = aggregateSeriesStats([mapOne, mapTwo]);
    expect(result!.participations[0].meta[12].seriesPlacement).toBe(1);
    expect(result!.participations[1].meta[21].seriesPlacement).toBe(1); // ties share a place
    expect(result!.participations[0].meta[11].seriesPlacement).toBe(3);
    expect(result!.participations[1].meta[22].seriesPlacement).toBeNull(); // no impact on any map
    const row = (id: number) =>
      result!.participations[0].players.find((entry) => entry.workspace_member_id === id)!.stats[0];
    expect(row(11)[LogStatsName.ImpactRank]).toBe(3);
    expect(row(11)[LogStatsName.ImpactPoints]).toBeUndefined();
  });

  it("groups by observed participation even when a map records the sides flipped", () => {
    const home = team(1, "A", [player(11, { [LogStatsName.Eliminations]: 7 }, [100])]);
    const away = team(2, "B", [player(21, { [LogStatsName.Eliminations]: 3 }, [200])]);
    const result = aggregateSeriesStats([statMatch(1, home, away), statMatch(2, away, home)]);
    expect(result!.participations[0].name).toBe("A");
    expect(result!.participations[0].players[0].stats[0][LogStatsName.Eliminations]).toBe(14);
    expect(result!.participations[1].players[0].stats[0][LogStatsName.Eliminations]).toBe(6);
  });

  it("counts event-only observed players without inventing heroes or an MVP placement", () => {
    const result = aggregateSeriesStats([
      statMatch(
        1,
        team(1, "A", [player(11, { [LogStatsName.Eliminations]: 5 }, [100]), player(12, {}, [])]),
        team(2, "B", [player(21, {}, [200])])
      )
    ]);
    expect(result!.participations[0].meta[11].mapsPlayed).toBe(1);
    expect(result!.participations[0].meta[12].mapsPlayed).toBe(1);
    expect(result!.participations[0].meta[12].seriesPlacement).toBeNull();
    expect(result!.participations[0].players[1].heroes[0]).toEqual([]);
    expect(result!.participations[0].players[1].stats[0]).toEqual({});
  });

  it("includes retired-only unbound observations without any live roster seats", () => {
    const home = team(107, "Archived A", [
      player(11, { [LogStatsName.Eliminations]: 10, [LogStatsName.HeroDamageDealt]: 125.25 }, [])
    ]);
    const away = team(108, "Archived B", [player(21, { [LogStatsName.Eliminations]: 4 }, [200])]);
    const observation = { ...statMatch(70, { ...home }, { ...away }, []), map_index: null };

    const result = aggregateSeriesStats([observation]);

    expect(result?.participations.map(({ id, name, live }) => ({ id, name, live }))).toEqual([
      { id: 107, name: "Archived A", live: false },
      { id: 108, name: "Archived B", live: false }
    ]);
    expect(result!.participations[0].players[0].stats[0][LogStatsName.Eliminations]).toBe(10);
    expect(result!.participations[0].players[0].stats[0][LogStatsName.HeroDamageDealt]).toBe(
      125.25
    );
    expect(result!.participations[1].players[0].stats[0][LogStatsName.Eliminations]).toBe(4);
    expect(result!.participations[0].meta[11].mapsPlayed).toBe(1);
    expect(teamTotal(result!.participations[0], 0, LogStatsName.HeroDamageDealt)).toBe(125.25);
    expect(result!.mapsCounted).toBe(1);
  });

  it("keeps historical and live participations distinct even when their player repeats", () => {
    const historical = (id: number) =>
      statMatch(
        id,
        team(101, "Old A", [
          player(
            11,
            {
              [LogStatsName.Eliminations]: 7,
              [LogStatsName.HeroDamageDealt]: 10.25,
              [LogStatsName.ImpactPoints]: 2,
              [LogStatsName.HeroTimePlayed]: 600
            },
            [100]
          )
        ]),
        team(102, "Old B", [player(21, { [LogStatsName.Eliminations]: 3 }, [200])]),
        [201, 202]
      );
    const current = statMatch(
      4,
      team(201, "Current A", [
        player(
          11,
          {
            [LogStatsName.Eliminations]: 2,
            [LogStatsName.HeroDamageDealt]: 1.5,
            [LogStatsName.ImpactPoints]: 1,
            [LogStatsName.HeroTimePlayed]: 600
          },
          [100]
        )
      ]),
      team(202, "Current B", [player(21, { [LogStatsName.Eliminations]: 3 }, [200])]),
      [201, 202]
    );
    const before = structuredClone({ a: historical(70), current });

    const result = aggregateSeriesStats([historical(70), current, historical(71)]);

    expect(result!.participations.map(({ id, name, live }) => ({ id, name, live }))).toEqual([
      { id: 101, name: "Old A", live: false },
      { id: 102, name: "Old B", live: false },
      { id: 201, name: "Current A", live: true },
      { id: 202, name: "Current B", live: true }
    ]);
    const oldA = result!.participations[0];
    const currentA = result!.participations[2];
    expect(oldA.players[0].stats[0][LogStatsName.Eliminations]).toBe(14);
    expect(oldA.players[0].stats[0][LogStatsName.HeroDamageDealt]).toBe(20.5);
    expect(currentA.players[0].stats[0][LogStatsName.Eliminations]).toBe(2);
    expect(currentA.players[0].stats[0][LogStatsName.HeroDamageDealt]).toBe(1.5);
    expect(oldA.meta[11].mapsPlayed).toBe(2);
    expect(currentA.meta[11].mapsPlayed).toBe(1);
    expect([oldA.meta[11].seriesPlacement, currentA.meta[11].seriesPlacement]).toEqual([1, 2]);
    expect(result!.mapsCounted).toBe(3);
    expect({ a: historical(70), current }).toEqual(before);
  });
});
