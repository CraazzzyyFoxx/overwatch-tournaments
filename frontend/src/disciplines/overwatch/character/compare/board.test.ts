import { describe, expect, it } from "vitest";

import type { CharacterLeaderboardEntry } from "@/types/statistics.types";

import { beatsShare, rankEntries, searchEntries, shareOfBest } from "./board";
import { COL } from "./stat-columns";

const row = (handle: string, games: number, elims: number, deaths: number): CharacterLeaderboardEntry => ({
  rank: 0, user_id: handle.length * 100 + games,
  display: { name: handle.slice(0, handle.lastIndexOf("#")), tag: handle.slice(handle.lastIndexOf("#")), canonical: handle, snapshot: null },
  role: null, div: 1, team: null,
  team_id: null, games_played: games, playtime_seconds: games * 600, per10_eliminations: elims, per10_healing: 0,
  per10_deaths: deaths, per10_damage: 0, per10_final_blows: 0, per10_damage_blocked: 0, per10_solo_kills: 0,
  per10_obj_kills: 0, per10_defensive_assists: 0, per10_offensive_assists: 0, per10_all_damage: 0,
  per10_damage_taken: 0, per10_self_healing: 0, per10_ultimates_used: 0, per10_multikills: 0, per10_env_kills: 0,
  per10_crit_hits: 0, avg_weapon_accuracy: 0, avg_crit_accuracy: 0, kd: 0, kda: 0
});

const ROWS = [
  row("Lucky#1", 1, 30, 9),
  row("Steady#2", 12, 14, 4),
  row("Solid#3", 6, 16, 6),
  row("Grinder#4", 40, 11, 3)
];

describe("the hero board", () => {
  it("leaves players under the sample floor off, then ranks the rest by the column", () => {
    const board = rankEntries(ROWS, 5, COL.per10_eliminations, "desc");
    expect(board.map(({ entry, rank }) => [rank, entry.display.name])).toEqual([
      [1, "Solid"],
      [2, "Steady"],
      [3, "Grinder"]
    ]);
  });

  it("ranks a lower-is-better column from its lowest value", () => {
    const board = rankEntries(ROWS, 1, COL.per10_deaths, "asc");
    expect(board.map(({ entry }) => entry.display.name)).toEqual(["Grinder", "Steady", "Solid", "Lucky"]);
  });

  it("keeps each match's rank on the whole board when a search narrows it", () => {
    const board = rankEntries(ROWS, 5, COL.per10_eliminations, "desc");
    expect(searchEntries(board, "  GRIND ").map(({ entry, rank }) => [rank, entry.display.name])).toEqual([[3, "Grinder"]]);
    // The canonical name finds a player their game names otherwise.
    expect(searchEntries(board, "solid#3").map(({ entry }) => entry.display.name)).toEqual(["Solid"]);
    expect(searchEntries(board, "")).toBe(board);
  });
});

describe("a bar's share of the column", () => {
  const sorted = [2, 4, 4, 9];

  it("counts the players a value beats, ties beating no one", () => {
    expect(beatsShare(sorted, 9, false)).toBe(1);
    expect(beatsShare(sorted, 4, false)).toBeCloseTo(1 / 3);
    expect(beatsShare(sorted, 2, false)).toBe(0);
  });

  it("turns around for a lower-is-better column", () => {
    expect(beatsShare(sorted, 2, true)).toBe(1);
    expect(beatsShare(sorted, 9, true)).toBe(0);
  });
});

describe("a top-chart bar", () => {
  it("is full for the leader and shorter for a weaker value, whichever way the column runs", () => {
    expect(shareOfBest(10, 10, false)).toBe(1);
    expect(shareOfBest(10, 5, false)).toBe(0.5);
    // Deaths: the leader died least, so twice the leader's deaths is half the leader's bar.
    expect(shareOfBest(2, 2, true)).toBe(1);
    expect(shareOfBest(2, 4, true)).toBe(0.5);
  });
});
