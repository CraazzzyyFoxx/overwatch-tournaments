import { describe, expect, it } from "vitest";

import type { CustomGamePlayer, RotationRecommendation } from "@/services/custom-game.service";

import { computeRotationHintPatches, sortLineup } from "./pickup-lineup";

function row(participation: "must_play" | "pool" | "benched", sortOrder = 0): CustomGamePlayer {
  return {
    id: sortOrder + 1,
    workspace_member_id: sortOrder + 7,
    display_name: null,
    battle_tag: null,
    participation,
    role_selection_mode: "all_ranked",
    sort_order: sortOrder,
    is_flex: false,
    roles: [],
    ranks: {},
    rank_sources: {},
    author_ranks: {},
  } as CustomGamePlayer;
}

function hint(status: "must_play" | "should_rest" | "neutral"): RotationRecommendation {
  return {
    workspace_member_id: 7,
    status,
    reason: "",
    consecutive_sat: 0,
    consecutive_played: 0,
    games_played: 0,
  };
}

describe("mix participation contract", () => {
  it("writes one enum when applying a rotation hint", () => {
    expect(computeRotationHintPatches([row("benched")], [hint("must_play")])).toEqual([
      { workspaceMemberId: 7, patch: { participation: "must_play" } },
    ]);
  });

  it("sorts pool and must-play rows ahead of benched rows", () => {
    expect(sortLineup([row("benched", 0), row("pool", 1)]).map((item) => item.participation)).toEqual([
      "pool",
      "benched",
    ]);
  });
});
