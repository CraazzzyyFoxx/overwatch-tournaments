import { describe, expect, it } from "vitest";

import type { CatalogEntityRead } from "@/types/catalog.types";
import type { CharacterStatBest, CharacterWithUserStats, UserMapRead } from "@/types/user.types";

import { LogStatsName } from "../stat-names";
import { heroMapRows, recordRows, sections, statRows, type StatRow } from "./hero-stats";

const entity = (id: number, name: string, kind: CatalogEntityRead["kind"]): CatalogEntityRead => ({
  active: true,
  aliases: [],
  attrs: {},
  created_at: "2026-01-01T00:00:00Z",
  discipline: "overwatch",
  id,
  image_path: null,
  kind,
  name,
  parent: null,
  parent_id: null,
  slug: name.toLowerCase(),
  updated_at: null
});

const game = (value: number, player = "Me#1"): CharacterStatBest => ({
  encounter_id: 7,
  map_image_path: "",
  map_name: "King's Row",
  player_name: player,
  tournament_name: "Cup #1",
  value
});

type Stat = CharacterWithUserStats["stats"][number];

const stat = (name: LogStatsName, avg10: number, average: number, extra: Partial<Stat> = {}): Stat => ({
  name,
  overall: avg10 * 10,
  avg_10: avg10,
  avg_10_all: average,
  best: game(avg10 * 3),
  best_all: game(avg10 * 4, "Other#2"),
  ...extra
});

const hero = (games: number, stats: Stat[]): CharacterWithUserStats => ({
  character: entity(1, "Cassidy", "character"),
  stats,
  games,
  win: 0,
  loss: games,
  draw: 0,
  win_rate_all: 0.5,
  record: null
});

const row = (rows: StatRow[], name: LogStatsName) => rows.find((r) => r.name === name);

describe("a hero's stat rows", () => {
  it("count a lower-is-better stat as a gain when the player is under the average", () => {
    const rows = statRows(
      hero(20, [
        stat(LogStatsName.DamageFB, 900, 1000),
        stat(LogStatsName.ShotsMissed, 88, 80),
        stat(LogStatsName.Eliminations, 12, 10)
      ])
    );
    expect(row(rows, LogStatsName.DamageFB)?.delta).toBeCloseTo(0.1);
    expect(row(rows, LogStatsName.ShotsMissed)?.delta).toBeCloseTo(-0.1);
    expect(row(rows, LogStatsName.Eliminations)?.delta).toBeCloseTo(0.2);
  });

  it("leave out what nobody does on the hero, but keep what only the player never did", () => {
    const rows = statRows(
      hero(20, [
        stat(LogStatsName.HealingDealt, 0, 0, { overall: 0 }),
        stat(LogStatsName.ObjectiveKills, 0, 3, { overall: 0 }),
        stat(LogStatsName.HeroTimePlayed, 450, 375)
      ])
    );
    expect(rows.map((r) => r.name)).toEqual([LogStatsName.ObjectiveKills]);
    expect(rows[0].delta).toBe(-1);
  });

  it("hide every comparison below the sample floor", () => {
    const stats = [stat(LogStatsName.Eliminations, 12, 10), stat(LogStatsName.Deaths, 5, 6)];
    expect(statRows(hero(9, stats)).map((r) => r.delta)).toEqual([null, null]);
    expect(statRows(hero(10, stats)).every((r) => r.delta !== null)).toBe(true);
  });

  it("call a best game a record only when higher is better, not a share, and something was done", () => {
    const rows = statRows(
      hero(20, [
        stat(LogStatsName.Deaths, 5, 6, { best: game(0), best_all: game(0, "Other#2") }),
        stat(LogStatsName.Eliminations, 12, 10, { best: game(44), best_all: game(58, "Mioto#1") }),
        stat(LogStatsName.HeroDamageDealt, 7000, 5000, { best: game(31011), best_all: game(31011) }),
        stat(LogStatsName.SoloKills, 1, 0.5, { best: game(0), best_all: game(9, "Other#2") }),
        stat(LogStatsName.WeaponAccuracy, 0.48, 0.41, { best: game(1), best_all: game(1, "Other#2") })
      ])
    );
    expect(row(rows, LogStatsName.Deaths)).toMatchObject({ best: null, record: null, holdsRecord: false });
    expect(row(rows, LogStatsName.Eliminations)).toMatchObject({ holdsRecord: false, record: { player_name: "Mioto#1" } });
    expect(row(rows, LogStatsName.HeroDamageDealt)?.holdsRecord).toBe(true);
    expect(row(rows, LogStatsName.SoloKills)).toMatchObject({ best: null, holdsRecord: false });
    expect(row(rows, LogStatsName.WeaponAccuracy)).toMatchObject({ best: null, record: null, holdsRecord: false });
  });

  it("give a stat read once per match no career total", () => {
    const rows = statRows(
      hero(20, [stat(LogStatsName.KD, 2.5, 2.4, { overall: 384 }), stat(LogStatsName.Eliminations, 12, 10, { overall: 1982 })])
    );
    expect(row(rows, LogStatsName.KD)?.total).toBeNull();
    expect(row(rows, LogStatsName.Eliminations)?.total).toBe(1982);
  });

  it("group in the catalogue's order, the stats it does not list last in their group", () => {
    const rows = statRows(
      hero(20, [
        stat(LogStatsName.WeaponAccuracy, 0.5, 0.4),
        stat(LogStatsName.FBE, 0.6, 0.5),
        stat(LogStatsName.HeroDamageDealt, 7000, 5000),
        stat(LogStatsName.FinalBlows, 8, 5),
        stat(LogStatsName.Eliminations, 12, 10)
      ])
    );
    expect(sections(rows).map((s) => [s.group, s.rows.map((r) => r.name)])).toEqual([
      ["combat", [LogStatsName.Eliminations, LogStatsName.FinalBlows, LogStatsName.FBE]],
      ["damage", [LogStatsName.HeroDamageDealt]],
      ["accuracy", [LogStatsName.WeaponAccuracy]]
    ]);
  });
});

describe("a hero's records", () => {
  it("lead with the class's headline stat", () => {
    const rows = statRows(
      hero(20, [
        stat(LogStatsName.Eliminations, 12, 10),
        stat(LogStatsName.HeroDamageDealt, 7000, 5000),
        stat(LogStatsName.HealingDealt, 9000, 8000)
      ])
    );
    expect(recordRows(rows, "support").map((r) => r.name)).toEqual([
      LogStatsName.HealingDealt,
      LogStatsName.HeroDamageDealt,
      LogStatsName.Eliminations
    ]);
  });
});

describe("a hero's maps", () => {
  it("read most played first, then by winrate", () => {
    const mapRow = (id: number, name: string, games: number, win: number): UserMapRead => ({
      map: entity(id, name, "map"),
      count: games,
      win,
      loss: games - win,
      draw: 0,
      win_rate: win / games,
      character_stats: [
        {
          character: entity(1, "Cassidy", "character"),
          games,
          win,
          loss: games - win,
          draw: 0,
          win_rate: win / games,
          playtime_seconds: 600,
          playtime_share_on_map: 1
        }
      ]
    });
    const maps = [mapRow(1, "Havana", 1, 1), mapRow(2, "King's Row", 16, 9), mapRow(3, "Midtown", 4, 3), mapRow(4, "Busan", 4, 1)];
    expect(heroMapRows(maps, 1).map((r) => r.map.name)).toEqual(["King's Row", "Midtown", "Busan", "Havana"]);
    expect(heroMapRows(maps, 2)).toEqual([]);
  });
});
