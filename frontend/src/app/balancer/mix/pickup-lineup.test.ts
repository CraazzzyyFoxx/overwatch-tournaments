import { describe, expect, it } from "vitest";

import type { CustomGamePlayer, RotationRecommendation } from "@/services/custom-game.service";

import {
  averageRank,
  computeRotationHintPatches,
  getLineupIssue,
  parseVariants,
  participationEntries,
  playerLabel,
  resolveRoleOrder,
  sortLineup,
  summarizeLineup,
  summarizeRoleSupply,
  teamNamesByIndex,
  toggleRole,
} from "./pickup-lineup";

function row(overrides: Partial<CustomGamePlayer> = {}): CustomGamePlayer {
  return {
    id: 1,
    workspace_member_id: 7,
    display_name: null,
    battle_tag: "Aria#1111",
    sort_order: 0,
    participation: "pool",
    role_selection_mode: "all_ranked",
    is_flex: false,
    roles: null,
    ranks: { tank: 2400, damage: 2600, support: 2500 },
    rank_sources: { tank: "workspace", damage: "workspace", support: "workspace" },
    author_ranks: {},
    ...overrides,
  };
}

function hint(overrides: Partial<RotationRecommendation> = {}): RotationRecommendation {
  return {
    workspace_member_id: 7,
    status: "neutral",
    reason: "",
    consecutive_sat: 0,
    consecutive_played: 0,
    games_played: 0,
    ...overrides,
  };
}

describe("computeRotationHintPatches", () => {
  it("seats a benched member who is owed a seat directly into Must Play", () => {
    const patches = computeRotationHintPatches(
      [row({ participation: "benched" })],
      [hint({ status: "must_play" })],
    );
    expect(patches).toEqual([{ workspaceMemberId: 7, patch: { participation: "must_play" } }]);
  });

  it("pins an already-active pool member who is owed a seat into Must Play", () => {
    const patches = computeRotationHintPatches(
      [row({ participation: "pool" })],
      [hint({ status: "must_play" })],
    );
    expect(patches).toEqual([{ workspaceMemberId: 7, patch: { participation: "must_play" } }]);
  });

  it("leaves an already-pinned must_play member untouched", () => {
    const patches = computeRotationHintPatches(
      [row({ participation: "must_play" })],
      [hint({ status: "must_play" })],
    );
    expect(patches).toEqual([]);
  });

  it("benches an active member who should rest, exactly like a manual drop into Benched", () => {
    const patches = computeRotationHintPatches(
      [row({ participation: "pool" })],
      [hint({ status: "should_rest" })],
    );
    expect(patches).toEqual([{ workspaceMemberId: 7, patch: { participation: "benched" } }]);
  });

  it("clears a stale host pin when benching a should_rest member", () => {
    const patches = computeRotationHintPatches(
      [row({ participation: "must_play" })],
      [hint({ status: "should_rest" })],
    );
    expect(patches).toEqual([{ workspaceMemberId: 7, patch: { participation: "benched" } }]);
  });

  it("leaves an already-benched should_rest member untouched", () => {
    const patches = computeRotationHintPatches(
      [row({ participation: "benched" })],
      [hint({ status: "should_rest" })],
    );
    expect(patches).toEqual([]);
  });

  it("never patches a neutral verdict", () => {
    const patches = computeRotationHintPatches(
      [row({ participation: "benched" })],
      [hint({ status: "neutral" })],
    );
    expect(patches).toEqual([]);
  });

  it("skips a member with no hint at all", () => {
    const patches = computeRotationHintPatches([row({ workspace_member_id: 9, participation: "benched" })], []);
    expect(patches).toEqual([]);
  });

  it("applies only the rows that actually need to change, across a mixed pool", () => {
    const rows = [
      row({ workspace_member_id: 1, participation: "benched" }), // owed a seat
      row({ workspace_member_id: 2, participation: "pool" }), // should rest
      row({ workspace_member_id: 3, participation: "pool" }), // neutral, no change
    ];
    const recommendations = [
      hint({ workspace_member_id: 1, status: "must_play" }),
      hint({ workspace_member_id: 2, status: "should_rest" }),
      hint({ workspace_member_id: 3, status: "neutral" }),
    ];
    expect(computeRotationHintPatches(rows, recommendations)).toEqual([
      { workspaceMemberId: 1, patch: { participation: "must_play" } },
      { workspaceMemberId: 2, patch: { participation: "benched" } },
    ]);
  });
});

describe("summarizeRoleSupply", () => {
  it("counts a player once per role they both picked and are ranked for", () => {
    expect(
      summarizeRoleSupply([
        row({ workspace_member_id: 1, roles: ["tank", "damage"] }),
        row({ workspace_member_id: 2, roles: ["support"] }),
      ]),
    ).toEqual([
      { role: "tank", supply: 1, need: 2, short: 1 },
      { role: "damage", supply: 1, need: 4, short: 3 },
      { role: "support", supply: 1, need: 4, short: 3 },
    ]);
  });

  it("does not count a selected role the player has no rank for", () => {
    // The balance refuses to seat it, so it is not supply however lit the chip is.
    const supply = summarizeRoleSupply([row({ roles: ["tank"], ranks: { damage: 2600 } })]);
    expect(supply.find((entry) => entry.role === "tank")).toEqual({
      role: "tank",
      supply: 0,
      need: 2,
      short: 2,
    });
  });

  it("ignores benched players entirely", () => {
    const supply = summarizeRoleSupply([row({ participation: "benched", roles: ["tank"] })]);
    expect(supply.every((entry) => entry.supply === 0)).toBe(true);
  });

  it("never reports a negative shortfall once a role is oversupplied", () => {
    const rows = Array.from({ length: 5 }, (_unused, index) =>
      row({ workspace_member_id: index + 1, roles: ["tank"] }),
    );
    expect(summarizeRoleSupply(rows)[0]).toEqual({ role: "tank", supply: 5, need: 2, short: 0 });
  });
});

describe("teamNamesByIndex", () => {
  it("re-keys the host's overrides by team index, dropping blanks", () => {
    expect(
      teamNamesByIndex({
        points_per_win: 0,
        team_names: { "0": "Wolves", "1": "   ", "2": "Bears" },
        workspace_discord_channel_id: null,
      }),
    ).toEqual({ 0: "Wolves", 2: "Bears" });
  });

  it("has nothing to say for a mix with no overrides at all", () => {
    expect(teamNamesByIndex(undefined)).toEqual({});
  });
});

describe("participationEntries", () => {
  it("flattens the hint patches into one whole-lineup payload", () => {
    expect(
      participationEntries([
        { workspaceMemberId: 7, patch: { participation: "must_play" } },
        { workspaceMemberId: 8, patch: { participation: "benched" } },
        // A patch that carries no participation is not a lineup move.
        { workspaceMemberId: 9, patch: { is_flex: true } },
      ]),
    ).toEqual([
      { workspace_member_id: 7, participation: "must_play" },
      { workspace_member_id: 8, participation: "benched" },
    ]);
  });
});

describe("resolveRoleOrder", () => {
  it("expands an unset role list to the ranked roles the balancer would use", () => {
    expect(resolveRoleOrder(row({ roles: null, ranks: { damage: 2600, support: 2500 } }))).toEqual([
      "damage",
      "support",
    ]);
  });

  it("keeps the stored selection and drops codes the balancer cannot use", () => {
    expect(resolveRoleOrder(row({ roles: ["support", "flex", "tank", "support"] }))).toEqual([
      "support",
      "tank",
    ]);
  });
});

describe("toggleRole", () => {
  it("appends a role that was off to the end of the order", () => {
    expect(toggleRole(["tank"], "support")).toEqual(["tank", "support"]);
  });

  it("removes a role that was on, leaving the rest of the order untouched", () => {
    expect(toggleRole(["tank", "damage", "support"], "damage")).toEqual(["tank", "support"]);
  });

  it("never resorts the roles it did not touch", () => {
    const afterTank = toggleRole([], "tank");
    const afterDamage = toggleRole(afterTank, "damage");
    // Tank was picked first, so it stays first however the ranks compare.
    expect(afterDamage).toEqual(["tank", "damage"]);
  });
});

describe("getLineupIssue", () => {
  it("stays silent for a benched player, whatever their setup", () => {
    expect(getLineupIssue(row({ participation: "benched", roles: [], ranks: {} }))).toBeNull();
  });

  it("flags an active player whose selected roles have no rank", () => {
    expect(getLineupIssue(row({ roles: ["tank"], ranks: { damage: 2600 } }))).toBe("no_rank");
  });

  it("flags an active player with every role switched off", () => {
    expect(getLineupIssue(row({ roles: [] }))).toBe("no_role");
  });

  it("passes a player with one ranked role", () => {
    expect(getLineupIssue(row({ roles: ["damage"], ranks: { damage: 2600 } }))).toBeNull();
  });
});

describe("averageRank", () => {
  it("averages only the roles the player will be assigned", () => {
    expect(averageRank(row({ roles: ["tank"], ranks: { tank: 2400, damage: 3000 } }))).toBe(2400);
  });

  it("has no value when nothing is ranked", () => {
    expect(averageRank(row({ roles: ["tank"], ranks: {} }))).toBeNull();
  });
});

describe("summarizeLineup", () => {
  it("counts participation and blockers separately from membership", () => {
    expect(
      summarizeLineup([
        row({ workspace_member_id: 1 }),
        row({ workspace_member_id: 2, participation: "benched" }),
        row({ workspace_member_id: 3, roles: [] }),
      ]),
    ).toEqual({ total: 3, active: 2, benched: 1, blocking: 1 });
  });
});

describe("sortLineup", () => {
  it("floats active players above benched ones, then keeps the host order", () => {
    const rows = [
      row({ workspace_member_id: 1, sort_order: 2 }),
      row({ workspace_member_id: 2, sort_order: 0, participation: "benched" }),
      row({ workspace_member_id: 3, sort_order: 1 }),
    ];
    expect(sortLineup(rows).map((item) => item.workspace_member_id)).toEqual([3, 1, 2]);
  });
});

describe("parseVariants", () => {
  const payload = {
    players: {
      "7": { name: "karin", ratings: { Tank: 2900 }, role_preferences: ["Tank"] },
      "8": {
        name: "DemonDimon",
        ratings: { Tank: 3900, Damage: 4100 },
        is_flex: false,
        role_preferences: ["Tank", "Damage"],
        sub_roles: { Damage: "hitscan" },
      },
      "9": { name: "Tolgrn" },
      "10": { name: "Egor", ratings: { Support: 2500 } },
    },
    feasibility: { structural_min_off_role: 1 },
    variants: [
      {
        teams: [
          { id: 1, average_mmr: 3000, total_rating: 15000, roster: { Damage: ["8"], Tank: ["7"] } },
          { id: 2, average_mmr: 2950, roster: { Support: ["9"] } },
        ],
        statistics: {
          mix_balancer_quality_total: 41.5,
          mix_balancer_role_fairness: 120.4,
          composite_score: 0.87,
          mmr_std_dev: 12.34,
          max_total_rating_gap: 150,
          off_role_count: 1,
          off_role_above_minimum: 0,
          sub_role_collision_count: 2,
        },
        benched: ["10"],
      },
      { teams: [] },
    ],
  };

  it("returns one entry per solver option", () => {
    expect(parseVariants(payload)).toHaveLength(2);
  });

  it("flattens role buckets into seats in canonical role order", () => {
    const [first] = parseVariants(payload);
    expect(first.teams[0].seats.map((seat) => [seat.role, seat.name])).toEqual([
      ["tank", "karin"],
      ["damage", "DemonDimon"],
    ]);
    expect(first.teams[0].averageRank).toBe(3000);
  });

  it("seats a player at the rating and sub-role of the bucket they sit in", () => {
    const [first] = parseVariants(payload);
    const [karin, demon] = first.teams[0].seats;
    expect(karin.rating).toBe(2900);
    // Rated for tank too, but seated at damage: the damage rating, not the best one.
    expect(demon.rating).toBe(4100);
    expect(demon.subRole).toBe("hitscan");
    expect(karin.subRole).toBeNull();
  });

  it("marks a seat off-role only when it is not the player's first choice", () => {
    const [first] = parseVariants(payload);
    const seats = first.teams[0].seats;
    expect(seats.find((seat) => seat.name === "karin")?.offRole).toBe(false);
    expect(seats.find((seat) => seat.name === "DemonDimon")?.offRole).toBe(true);
  });

  it("never marks a flex player off-role", () => {
    const [variant] = parseVariants({
      players: { "1": { name: "Flexy", is_flex: true, role_preferences: ["Tank"] } },
      variants: [{ teams: [{ roster: { Support: ["1"] } }] }],
    });
    expect(variant.teams[0].seats[0].offRole).toBe(false);
    expect(variant.teams[0].seats[0].isFlex).toBe(true);
  });

  it("carries the stats and the benched names the pager shows", () => {
    const [first] = parseVariants(payload);
    expect(first.stats).toEqual({
      qualityScore: 41.5,
      mmrStdDev: 12.34,
      ratingGap: 150,
      lineGap: 120.4,
      offRoleCount: 1,
      offRoleAboveMinimum: 0,
      offRoleFloor: 1,
      subRoleCollisions: 2,
      benchedCount: 1,
    });
    expect(first.benched).toEqual(["Egor"]);
  });

  it("falls back to the tournament solver's score when the mix engine did not run", () => {
    // The Linux-only mix engine is missing in some images, and `run_mix_balance`
    // then falls back to `tournament_balancer`, which scores with
    // `composite_score` instead. One pill, whichever engine ran.
    const [variant] = parseVariants({
      players: { "7": { name: "karin" } },
      variants: [{ teams: [{ roster: { tank: ["7"] } }], statistics: { composite_score: 0.87 } }],
    });
    expect(variant.stats.qualityScore).toBe(0.87);
  });

  it("reports no score for a hand-edited option the solver no longer owns", () => {
    // `_recompute_variant_stats` nulls every solver-scored key after a seat
    // swap; a null must read as absent, never as a genuine 0.
    const [variant] = parseVariants({
      players: { "7": { name: "karin" } },
      variants: [
        {
          teams: [{ roster: { tank: ["7"] } }],
          statistics: {
            composite_score: null,
            mix_balancer_quality_total: null,
            mix_balancer_role_fairness: null,
            off_role_count: 2,
          },
        },
      ],
    });
    expect(variant.stats.qualityScore).toBeNull();
    expect(variant.stats.lineGap).toBeNull();
    expect(variant.stats.offRoleCount).toBe(2);
  });

  it("degrades to an empty list instead of throwing on an unknown shape", () => {
    expect(parseVariants(null)).toEqual([]);
    expect(parseVariants({ variants: "nope" })).toEqual([]);
    expect(parseVariants({ variants: [{ teams: [{ roster: ["7"] }] }] })[0].teams).toEqual([]);
    // A seat whose uuid the players map does not know is dropped, not invented.
    expect(
      parseVariants({ players: {}, variants: [{ teams: [{ roster: { tank: ["ghost"] } }] }] })[0].teams[0].seats,
    ).toEqual([]);
  });
});

describe("playerLabel", () => {
  it("prefers a display name, then the tag, then the id", () => {
    expect(playerLabel(row({ display_name: "Aria" }))).toBe("Aria");
    expect(playerLabel(row({ display_name: null }))).toBe("Aria#1111");
    expect(playerLabel(row({ display_name: null, battle_tag: null }))).toBe("#7");
  });
});
