import { describe, expect, it } from "vitest";

import type { PlayerStanding } from "@/types/admin.types";

import { cutIndex, pinOf, pinsDirty, pinsPayload, tablesByRole } from "./playerStandings.model";

const row = (
  member: number,
  role: string,
  position: number,
  overrides: Partial<PlayerStanding> = {}
): PlayerStanding => ({
  stage_id: 1,
  workspace_member_id: member,
  registration_id: member,
  display_name: `P${member}`,
  role,
  rank: 3000,
  position,
  points: 0,
  wins: 0,
  draws: 0,
  losses: 0,
  maps_won: 0,
  maps_lost: 0,
  map_diff: 0,
  buchholz: 0,
  matches_played: 0,
  is_qualified: false,
  is_captain: false,
  is_pinned: false,
  ...overrides
});

describe("player standings model", () => {
  it("groups one stage's rows by role in the server's order", () => {
    const rows = [row(1, "tank", 1), row(2, "tank", 2), row(3, "damage", 1), row(4, "tank", 1, { stage_id: 2 })];
    expect(tablesByRole(rows, 1).map((table) => [table.role, table.rows.length])).toEqual([
      ["tank", 2],
      ["damage", 1]
    ]);
  });

  it("finds the last qualified row of a role", () => {
    expect(cutIndex([row(1, "tank", 1, { is_qualified: true }), row(2, "tank", 2)])).toBe(0);
    expect(cutIndex([row(1, "tank", 1)])).toBe(-1);
  });

  it("reads a saved pin off the row and lets a draft override or clear it", () => {
    const pinned = row(1, "tank", 3, { is_pinned: true });
    expect(pinOf(pinned, {})).toBe(3);
    expect(pinOf(pinned, { 1: 2 })).toBe(2);
    expect(pinOf(pinned, { 1: null })).toBeNull();
    expect(pinOf(row(2, "tank", 1), {})).toBeNull();
  });

  it("sends the whole pin set and is dirty only when it differs from the saved one", () => {
    const rows = [row(1, "tank", 3, { is_pinned: true }), row(2, "tank", 1), row(3, "damage", 2)];
    expect(pinsDirty(rows, {})).toBe(false);
    expect(pinsDirty(rows, { 1: 3 })).toBe(false);
    expect(pinsDirty(rows, { 2: 2 })).toBe(true);
    expect(pinsPayload(rows, { 2: 2, 1: null, 3: 1 })).toEqual([
      { workspace_member_id: 2, position: 2 },
      { workspace_member_id: 3, position: 1 }
    ]);
    // Unpinning everything is a real answer: the empty list.
    expect(pinsPayload(rows, { 1: null })).toEqual([]);
  });
});
