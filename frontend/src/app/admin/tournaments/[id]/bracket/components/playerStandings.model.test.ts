import { describe, expect, it } from "vitest";

import type { PlayerStanding } from "@/types/admin.types";

import { pinsDirty, pinsPayload, standingRows } from "./playerStandings.model";

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
  it("sizes each role and draws the cut under its last qualifier, only when someone is below", () => {
    const rows = standingRows(
      [
        row(1, "tank", 1, { is_qualified: true }),
        row(2, "tank", 2),
        row(3, "damage", 1, { is_qualified: true }),
        row(4, "damage", 2, { is_qualified: true }),
        row(5, "support", 1)
      ],
      {}
    );
    expect(rows.map((r) => [r.workspace_member_id, r.roleSize, r.atCut])).toEqual([
      [1, 2, true],
      [2, 2, false],
      [3, 2, false],
      [4, 2, false],
      [5, 1, false]
    ]);
  });

  it("reads a saved pin off the row and lets a draft override or clear it", () => {
    const pins = (edits: Record<number, number | null>) =>
      standingRows([row(1, "tank", 3, { is_pinned: true }), row(2, "tank", 1)], edits).map((r) => r.pin);
    expect(pins({})).toEqual([3, null]);
    expect(pins({ 1: 2 })).toEqual([2, null]);
    expect(pins({ 1: null, 2: 1 })).toEqual([null, 1]);
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
