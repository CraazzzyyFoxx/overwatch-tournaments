import { describe, expect, it } from "vitest";

import type { PlayerStanding } from "@/types/tournament.types";

import { orderPlayerStandings, playerStandingsCutAfter } from "./playerStandings.model";

function row(overrides: Partial<PlayerStanding>): PlayerStanding {
  return {
    stage_id: 1,
    workspace_member_id: 1,
    registration_id: null,
    display_name: "Player",
    role: "tank",
    rank: 1000,
    position: 1,
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
  };
}

const ids = (rows: readonly PlayerStanding[]) => rows.map((standing) => standing.workspace_member_id);

describe("orderPlayerStandings", () => {
  it("interleaves roles by place, keeping the API's role order on an equal place", () => {
    const ordered = orderPlayerStandings([
      row({ workspace_member_id: 1, role: "tank", position: 1, rank: 1000 }),
      row({ workspace_member_id: 2, role: "tank", position: 2 }),
      row({ workspace_member_id: 3, role: "damage", position: 1, rank: 4000 }),
      row({ workspace_member_id: 4, role: "damage", position: 2 }),
      row({ workspace_member_id: 5, role: "support", position: 1 })
    ]);

    expect(ids(ordered)).toEqual([1, 3, 5, 2, 4]);
  });

  it("puts unranked rows last, by rank", () => {
    const ordered = orderPlayerStandings([
      row({ workspace_member_id: 1, position: null, rank: 2000 }),
      row({ workspace_member_id: 2, position: null, rank: 3000 }),
      row({ workspace_member_id: 3, position: 1 })
    ]);

    expect(ids(ordered)).toEqual([3, 2, 1]);
  });
});

describe("playerStandingsCutAfter", () => {
  it("cuts under the last qualified row", () => {
    expect(
      playerStandingsCutAfter([
        row({ workspace_member_id: 1, is_qualified: true }),
        row({ workspace_member_id: 2, is_qualified: true }),
        row({ workspace_member_id: 3 })
      ])
    ).toBe(2);
  });

  it("draws no cut when nobody or everybody qualifies", () => {
    expect(playerStandingsCutAfter([row({ workspace_member_id: 1 })])).toBeNull();
    expect(
      playerStandingsCutAfter([
        row({ workspace_member_id: 1, is_qualified: true }),
        row({ workspace_member_id: 2, is_qualified: true })
      ])
    ).toBeNull();
  });
});
