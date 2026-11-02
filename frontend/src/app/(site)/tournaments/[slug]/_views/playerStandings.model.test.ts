import { describe, expect, it } from "vitest";

import type { PlayerStanding } from "@/types/tournament.types";

import { groupPlayerStandings } from "./playerStandings.model";

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

describe("groupPlayerStandings", () => {
  it("keeps roles in the API's order and puts the cut under the last qualified row", () => {
    const groups = groupPlayerStandings([
      row({ workspace_member_id: 1, role: "tank", position: 1, is_qualified: true }),
      row({ workspace_member_id: 2, role: "tank", position: 2 }),
      row({ workspace_member_id: 3, role: "damage", position: 1, is_qualified: true }),
      row({ workspace_member_id: 4, role: "damage", position: 2, is_qualified: true }),
      row({ workspace_member_id: 5, role: "damage", position: 3 })
    ]);

    expect(groups.map((group) => [group.role, group.rows.length, group.cutAfter])).toEqual([
      ["tank", 2, 0],
      ["damage", 3, 1]
    ]);
  });

  it("draws no cut when nobody or everybody qualifies", () => {
    const [none, all] = groupPlayerStandings([
      row({ workspace_member_id: 1, role: "tank", position: 1 }),
      row({ workspace_member_id: 2, role: "support", position: 1, is_qualified: true }),
      row({ workspace_member_id: 3, role: "support", position: 2, is_qualified: true })
    ]);

    expect(none.cutAfter).toBeNull();
    expect(all.cutAfter).toBeNull();
  });

  it("splits stages apart, sorts by place with unranked rows last, ties by rank", () => {
    const groups = groupPlayerStandings([
      row({ workspace_member_id: 1, stage_id: 1, position: null, rank: 2000 }),
      row({ workspace_member_id: 2, stage_id: 1, position: null, rank: 3000 }),
      row({ workspace_member_id: 3, stage_id: 1, position: 1 }),
      row({ workspace_member_id: 4, stage_id: 2, position: 1 })
    ]);

    expect(groups.map((group) => group.key)).toEqual(["1:tank", "2:tank"]);
    expect(groups[0].rows.map((standing) => standing.workspace_member_id)).toEqual([3, 2, 1]);
  });
});
