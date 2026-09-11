import { describe, expect, it } from "vitest";

import type { MixMemberStats } from "@/services/custom-game.service";

import { formatRecord, formatStreak, leaderboardRows, sinceFor } from "./pickup-stats";

function member(overrides: Partial<MixMemberStats> = {}): MixMemberStats {
  return {
    workspace_member_id: 1,
    display_name: "Aria",
    battle_tag: "Aria#1111",
    games: 10,
    wins: 6,
    losses: 4,
    draws: 0,
    win_rate: 0.6,
    streak: 2,
    last_played_at: "2026-01-05T20:00:00Z",
    by_role: { tank: { games: 10, wins: 6, losses: 4, draws: 0 } },
    ...overrides,
  };
}

describe("sinceFor", () => {
  it("counts a window back from now, not from a calendar boundary", () => {
    const now = new Date("2026-01-10T13:45:00.000Z");

    expect(sinceFor("7d", now)).toBe("2026-01-03T13:45:00.000Z");
    expect(sinceFor("30d", now)).toBe("2025-12-11T13:45:00.000Z");
  });

  it("filters nothing for all time", () => {
    expect(sinceFor("all", new Date("2026-01-10T13:45:00.000Z"))).toBeNull();
  });
});

describe("leaderboardRows", () => {
  it("drops records too short to rank, keeping the server's order", () => {
    const rows = leaderboardRows(
      [
        member({ workspace_member_id: 1, games: 9 }),
        member({ workspace_member_id: 2, games: 2 }),
        member({ workspace_member_id: 3, games: 3 }),
      ],
      3,
    );

    expect(rows.map((row) => row.workspace_member_id)).toEqual([1, 3]);
  });
});

describe("formatStreak", () => {
  it("reads a run as its direction and length", () => {
    expect(formatStreak(3)).toBe("W3");
    expect(formatStreak(-2)).toBe("L2");
  });

  it("has nothing to show once a run is broken", () => {
    expect(formatStreak(0)).toBeNull();
  });
});

describe("formatRecord", () => {
  it("names draws only when there are some", () => {
    expect(formatRecord(member({ wins: 12, losses: 8, draws: 0 }))).toBe("12–8");
    expect(formatRecord(member({ wins: 12, losses: 8, draws: 1 }))).toBe("12–8–1");
  });
});
