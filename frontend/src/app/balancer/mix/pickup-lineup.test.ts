import { describe, expect, it } from "vitest";

import { slotCodeOrder } from "@/lib/roster/ontology";
import type { CustomGame, CustomGamePlayer, RotationRecommendation } from "@/services/custom-game.service";
import { LOL_METADATA, OW_METADATA } from "@/test/discipline-metadata";
import { TEST_LADDER_TIERS } from "@/test/native-ladder";

import {
  averageRank,
  buildMixOwner,
  canWriteMix,
  computeRotationHintPatches,
  getLineupIssue,
  isMixHost,
  lobbyCandidateCount,
  myLobbyTeam,
  parseVariants as parseVariantsOrdered,
  participationEntries,
  playerLabel,
  rankSourceLabel,
  resolveRoleOrder,
  sortLineup,
  summarizeLineup,
  summarizeRoleSupply,
  teamNamesByIndex,
  toggleRole,
  waitingQueuePosition,
} from "./pickup-lineup";
import { DEADLOCK_OWNER, LOL_OWNER, LOL_SHAPE, OW_OWNER, OW_SHAPE, flexOnlyOwner } from "./mix-owner.fixture";

const OW_ORDER = slotCodeOrder(OW_METADATA);
const LOL_ORDER = slotCodeOrder(LOL_METADATA);

/** The caller's numbered default for a team the host has not renamed. */
const teamN = (index: number) => `Team ${index + 1}`;

/** The Overwatch mix's variants, seats ordered by the game's declared role order. */
const parseVariants = (resultJson: unknown, teamNames: Record<number, string> = {}) =>
  parseVariantsOrdered(resultJson, teamNames, OW_ORDER, teamN);

function row(overrides: Partial<CustomGamePlayer> = {}): CustomGamePlayer {
  return {
    id: 1,
    workspace_member_id: 7,
    display_name: null,
    identity: { provider: "battlenet", handle: "Aria#1111" },
    sort_order: 0,
    participation: "pool",
    role_selection_mode: "all_ranked",
    is_flex: false,
    away: false,
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
    reason: "default",
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

  it("never moves an away member, whatever a cached verdict says", () => {
    const rows = [
      row({ workspace_member_id: 1, participation: "benched", away: true }),
      row({ workspace_member_id: 2, participation: "pool", away: true }),
    ];
    const recommendations = [
      hint({ workspace_member_id: 1, status: "must_play" }),
      hint({ workspace_member_id: 2, status: "should_rest" }),
    ];
    expect(computeRotationHintPatches(rows, recommendations)).toEqual([]);
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

describe("buildMixOwner", () => {
  it("derives Overwatch's lineup demand 2/4/4 and lobby of ten from its 1-2-2 roster shape", () => {
    expect(OW_OWNER.roles).toEqual(["tank", "damage", "support"]);
    expect(OW_OWNER.demand).toEqual({ tank: 2, damage: 4, support: 4 });
    expect(OW_OWNER.lobbySize).toBe(10);
    expect(OW_OWNER.dimension).toBe("player_role");
  });

  it("derives League's five positions, two seats each and a lobby of ten, from its roster shape", () => {
    expect(LOL_OWNER.roles).toEqual(["top", "jungle", "mid", "bot", "support"]);
    expect(LOL_OWNER.demand).toEqual({ top: 2, jungle: 2, mid: 2, bot: 2, support: 2 });
    expect(LOL_OWNER.lobbySize).toBe(10);
    expect(LOL_OWNER.dimension).toBe("position");
  });

  it("reads a different format of the same game from the shape, not from the game", () => {
    const duo = buildMixOwner(LOL_METADATA, { ...LOL_SHAPE, slots: { top: 1, mid: 1 }, team_size: 2 }, { tiers: [] });
    expect(duo.demand).toEqual({ top: 2, mid: 2 });
    expect(duo.lobbySize).toBe(4);
  });

  it("a flex-only format asks no role of anyone but still fills a lobby", () => {
    const owner = flexOnlyOwner();
    expect(owner.demand).toEqual({});
    expect(owner.lobbySize).toBe(10);
  });

  it("reads a one-role game without Full flex: Deadlock seats agents only and names no role", () => {
    expect(DEADLOCK_OWNER).toMatchObject({
      roles: ["agent"],
      dimension: "agent",
      demand: { agent: 12 },
      lobbySize: 12,
      flex: false,
      showsRoles: false,
    });
    expect(OW_OWNER).toMatchObject({ flex: true, showsRoles: true });
  });

  it("is empty until metadata and shape load: nothing is guessed", () => {
    const pending = buildMixOwner(undefined, null, { tiers: [] });
    expect(pending).toMatchObject({ ontology: null, dimension: null, roles: [], demand: {}, lobbySize: null });
  });

  it("reads ranks on the game's global ladder, not the workspace's tournament grid", () => {
    // A workspace running tournament divisions 1-20 (top tier from 2000) must not turn every 3500 into Division 1.
    const workspaceGrid = { tiers: [{ number: 1, name: "Division 1", rank_min: 2000, rank_max: null, icon_url: "" }] };
    const owner = buildMixOwner({ ...OW_METADATA, native_ladder: TEST_LADDER_TIERS }, OW_SHAPE, workspaceGrid);
    expect(owner.grid.tiers.map((tier) => tier.name)).toEqual(TEST_LADDER_TIERS.map((tier) => tier.name));
  });

  it("falls back to the workspace grid only for a game without a ladder", () => {
    const workspaceGrid = { tiers: [{ number: 1, name: "Division 1", rank_min: 2000, rank_max: null, icon_url: "" }] };
    expect(buildMixOwner({ ...OW_METADATA, native_ladder: [] }, OW_SHAPE, workspaceGrid).grid).toBe(workspaceGrid);
  });

  it("names the native rank layer after the game, and every other layer by the caller's label", () => {
    const layerLabel = (source: string) => `layer:${source}`;
    expect(rankSourceLabel("native", "League of Legends", layerLabel)).toBe("League of Legends");
    expect(rankSourceLabel("native", null, layerLabel)).toBe("layer:native");
    expect(rankSourceLabel("author", "League of Legends", layerLabel)).toBe("layer:author");
  });
});

describe("summarizeRoleSupply", () => {
  it("counts a player once per role they both picked and are ranked for", () => {
    expect(
      summarizeRoleSupply(
        [
          row({ workspace_member_id: 1, roles: ["tank", "damage"].map((role) => ({ dimension: "player_role", role })) }),
          row({ workspace_member_id: 2, roles: [{ dimension: "player_role", role: "support" }] }),
        ],
        OW_OWNER,
      ),
    ).toEqual([
      { role: "tank", supply: 1, need: 2, short: 1 },
      { role: "damage", supply: 1, need: 4, short: 3 },
      { role: "support", supply: 1, need: 4, short: 3 },
    ]);
  });

  it("does not count a selected role the player has no rank for", () => {
    // The balance refuses to seat it, so it is not supply however lit the chip is.
    const supply = summarizeRoleSupply([row({ roles: [{ dimension: "player_role", role: "tank" }], ranks: { damage: 2600 } })], OW_OWNER);
    expect(supply.find((entry) => entry.role === "tank")).toEqual({
      role: "tank",
      supply: 0,
      need: 2,
      short: 2,
    });
  });

  it("ignores benched players entirely", () => {
    const supply = summarizeRoleSupply([row({ participation: "benched", roles: [{ dimension: "player_role", role: "tank" }] })], OW_OWNER);
    expect(supply.every((entry) => entry.supply === 0)).toBe(true);
  });

  it("does not count away players: with both tanks away the tank seats stay short", () => {
    const tank = [{ dimension: "player_role", role: "tank" }];
    const supply = summarizeRoleSupply(
      [
        row({ workspace_member_id: 1, roles: tank, away: true }),
        row({ workspace_member_id: 2, roles: tank, away: true }),
        row({ workspace_member_id: 3, roles: [{ dimension: "player_role", role: "damage" }] }),
      ],
      OW_OWNER,
    );
    expect(supply.find((entry) => entry.role === "tank")).toEqual({ role: "tank", supply: 0, need: 2, short: 2 });
  });

  it("never reports a negative shortfall once a role is oversupplied", () => {
    const rows = Array.from({ length: 5 }, (_unused, index) =>
      row({ workspace_member_id: index + 1, roles: [{ dimension: "player_role", role: "tank" }] }),
    );
    expect(summarizeRoleSupply(rows, OW_OWNER)[0]).toEqual({ role: "tank", supply: 5, need: 2, short: 0 });
  });

  it("multiplies the demand by the lobbies the mix runs", () => {
    expect(summarizeRoleSupply([], OW_OWNER, 3).map((entry) => entry.need)).toEqual([6, 12, 12]);
  });

  it("counts League's five positions against two seats each, one entry per position", () => {
    const rows = ["top", "jungle", "mid", "bot", "support"].map((position, index) =>
      row({
        workspace_member_id: index + 1,
        roles: [{ dimension: "position", role: position }],
        ranks: { [position]: 2000 + index },
      }),
    );
    expect(summarizeRoleSupply(rows, LOL_OWNER)).toEqual([
      { role: "top", supply: 1, need: 2, short: 1 },
      { role: "jungle", supply: 1, need: 2, short: 1 },
      { role: "mid", supply: 1, need: 2, short: 1 },
      { role: "bot", supply: 1, need: 2, short: 1 },
      { role: "support", supply: 1, need: 2, short: 1 },
    ]);
  });

  it("has no entry for a game whose format asks no role of anyone", () => {
    expect(summarizeRoleSupply([row()], flexOnlyOwner())).toEqual([]);
  });

  it("has no entry for a one-role game, though every seat is that role", () => {
    expect(summarizeRoleSupply([row({ ranks: { agent: 2400 } })], DEADLOCK_OWNER)).toEqual([]);
  });
});

describe("teamNamesByIndex", () => {
  const SETTINGS = {
    points_per_win: 0,
    // Global indices: 0-1 are lobby A's two teams, 2-3 are lobby B's.
    team_names: { "0": "Wolves", "1": "   ", "2": "Bears", "3": "Ravens" },
    workspace_discord_channel_id: null,
  };

  it("re-keys lobby A's overrides by team index, dropping blanks and lobby B's", () => {
    expect(teamNamesByIndex(SETTINGS)).toEqual({ 0: "Wolves" });
  });

  it("shifts lobby B's overrides down to the positions its own two teams render at", () => {
    expect(teamNamesByIndex(SETTINGS, 1)).toEqual({ 0: "Bears", 1: "Ravens" });
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
    expect(resolveRoleOrder(row({ roles: null, ranks: { damage: 2600, support: 2500 } }), OW_OWNER.roles)).toEqual([
      "damage",
      "support",
    ]);
  });

  it("orders the ranked roles by the game's declared order, not by the rank map's key order", () => {
    expect(
      resolveRoleOrder(row({ roles: null, ranks: { support: 2500, damage: 2600, tank: 2400 } }), OW_OWNER.roles),
    ).toEqual(["tank", "damage", "support"]);
    expect(
      resolveRoleOrder(row({ roles: null, ranks: { bot: 2000, top: 2200, mid: 2100 } }), LOL_OWNER.roles),
    ).toEqual(["top", "mid", "bot"]);
  });

  it("keeps the stored selection in the host's order and never treats the open slot as a role", () => {
    expect(resolveRoleOrder(row({
      roles: ["support", "flex", "tank", "support"].map((role) => ({ dimension: "player_role", role })),
    }), OW_OWNER.roles)).toEqual(["support", "tank"]);
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
    expect(getLineupIssue(row({ participation: "benched", roles: [], ranks: {} }), OW_OWNER.roles)).toBeNull();
  });

  it("stays silent for an away player without a ranked role: the balance skips them", () => {
    expect(getLineupIssue(row({ away: true, roles: [] }), OW_OWNER.roles)).toBeNull();
  });

  it("flags an active player whose selected roles have no rank", () => {
    expect(getLineupIssue(row({ roles: [{ dimension: "player_role", role: "tank" }], ranks: { damage: 2600 } }), OW_OWNER.roles)).toBe("no_rank");
  });

  it("flags an active player with every role switched off", () => {
    expect(getLineupIssue(row({ roles: [] }), OW_OWNER.roles)).toBe("no_role");
  });

  it("passes a player with one ranked role", () => {
    expect(getLineupIssue(row({ roles: [{ dimension: "player_role", role: "damage" }], ranks: { damage: 2600 } }), OW_OWNER.roles)).toBeNull();
  });

  it("reads a League player's positions, not Overwatch's: a ranked position clears the warning", () => {
    const jungler = row({ roles: [{ dimension: "position", role: "jungle" }], ranks: { jungle: 2100 } });
    expect(getLineupIssue(jungler, LOL_OWNER.roles)).toBeNull();
    expect(getLineupIssue({ ...jungler, ranks: { top: 2100 } }, LOL_OWNER.roles)).toBe("no_rank");
  });
});

describe("averageRank", () => {
  it("averages only the roles the player will be assigned", () => {
    expect(averageRank(row({ roles: [{ dimension: "player_role", role: "tank" }], ranks: { tank: 2400, damage: 3000 } }), OW_OWNER.roles)).toBe(2400);
  });

  it("has no value when nothing is ranked", () => {
    expect(averageRank(row({ roles: [{ dimension: "player_role", role: "tank" }], ranks: {} }), OW_OWNER.roles)).toBeNull();
  });
});

describe("summarizeLineup", () => {
  it("counts participation and blockers separately from membership", () => {
    expect(
      summarizeLineup(
        [
          row({ workspace_member_id: 1 }),
          row({ workspace_member_id: 2, participation: "benched" }),
          row({ workspace_member_id: 3, roles: [] }),
        ],
        OW_OWNER.roles,
      ),
    ).toEqual({ total: 3, active: 2, benched: 1, blocking: 1 });
  });

  it("leaves away players out of the balance count and its blockers, without calling them benched", () => {
    expect(
      summarizeLineup(
        [
          row({ workspace_member_id: 1 }),
          row({ workspace_member_id: 2, participation: "benched" }),
          row({ workspace_member_id: 3, away: true, roles: [], ranks: {} }),
        ],
        OW_OWNER.roles,
      ),
    ).toEqual({ total: 3, active: 1, benched: 1, blocking: 0 });
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

  it("carries the host's open rating for the seated bucket, and nothing in points mode", () => {
    const [variant] = parseVariants({
      players: {
        "7": { name: "karin", ratings: { Tank: 2650 }, open_ratings: { Tank: 2400, Damage: 3100 } },
        "8": { name: "Tolgrn", ratings: { Damage: 3000 } },
      },
      variants: [{ teams: [{ roster: { Tank: ["7"], Damage: ["8"] } }] }],
    });
    const [karin, tolgrn] = variant.teams[0].seats;
    expect(karin.rating).toBe(2650);
    // The bucket they sit in, not the best open rating they have.
    expect(karin.openRating).toBe(2400);
    // No `open_ratings` at all: points mode, nothing extra to show.
    expect(tolgrn.openRating).toBeNull();
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
    expect(playerLabel(row({ display_name: null, identity: null }))).toBe("#7");
  });
});

describe("parseVariants for a League mix", () => {
  const players = {
    "1": { name: "Zed", ratings: { top: 2100 }, role_preferences: ["top"] },
    "2": { name: "Lee", ratings: { jungle: 2200 }, role_preferences: ["jungle"] },
    "3": { name: "Ahri", ratings: { mid: 2300 }, role_preferences: ["mid"] },
    "4": { name: "Jinx", ratings: { bot: 2400 }, role_preferences: ["bot"] },
    "5": { name: "Lulu", ratings: { support: 2500 }, role_preferences: ["support", "bot"] },
    "6": { name: "Sub", ratings: { mid: 2000 }, role_preferences: ["top"] },
  };

  it("keeps every seated player, in the game's position order", () => {
    const [variant] = parseVariantsOrdered(
      {
        players,
        variants: [
          {
            // The solver's buckets arrive in any order; none of them is Overwatch's.
            teams: [{ id: 1, roster: { support: ["5"], bot: ["4"], mid: ["3"], jungle: ["2"], top: ["1"] } }],
          },
        ],
      },
      {},
      LOL_ORDER,
      teamN,
    );
    expect(variant.teams[0].seats.map((seat) => [seat.role, seat.name])).toEqual([
      ["top", "Zed"],
      ["jungle", "Lee"],
      ["mid", "Ahri"],
      ["bot", "Jinx"],
      ["support", "Lulu"],
    ]);
  });

  it("flags an off-position seat against the seat's own role, not a fixed vocabulary", () => {
    const [variant] = parseVariantsOrdered(
      { players, variants: [{ teams: [{ roster: { mid: ["6"], support: ["5"] } }] }] },
      {},
      LOL_ORDER,
      teamN,
    );
    const bySeat = Object.fromEntries(variant.teams[0].seats.map((seat) => [seat.name, seat.offRole]));
    expect(bySeat).toEqual({ Sub: true, Lulu: false });
  });

  it("keeps a capitalised legacy bucket, an open seat and an unknown bucket instead of dropping their players", () => {
    const [variant] = parseVariantsOrdered(
      {
        players: { ...players, "7": { name: "Open", is_flex: false, role_preferences: ["top"] } },
        variants: [{ teams: [{ roster: { Top: ["1"], flex: ["7"], coach: ["6"] } }] }],
      },
      {},
      LOL_ORDER,
      teamN,
    );
    const seats = variant.teams[0].seats;
    expect(seats.map((seat) => [seat.role, seat.name])).toEqual([
      ["top", "Zed"],
      ["flex", "Open"],
      ["coach", "Sub"],
    ]);
    // The rank follows the bucket: Zed's `ratings.top` is read for the `Top` bucket, not lost as 0.
    expect(seats.find((seat) => seat.name === "Zed")?.rating).toBe(2100);
    // An open seat names no role: nobody is off-role on it.
    expect(seats.find((seat) => seat.role === "flex")?.offRole).toBe(false);
  });

  it("reads ratings, open ratings and sub-roles under any casing of the bucket's key", () => {
    const [variant] = parseVariantsOrdered(
      {
        players: {
          "8": {
            name: "Cap",
            ratings: { Top: 2150 },
            open_ratings: { TOP: 2050 },
            sub_roles: { Top: "roamer" },
            role_preferences: ["Top"],
          },
          "9": {
            name: "Low",
            ratings: { top: 1900 },
            open_ratings: { top: 1800 },
            sub_roles: { top: "split" },
            role_preferences: ["top"],
          },
        },
        variants: [{ teams: [{ roster: { Top: ["8"] } }, { roster: { top: ["9"] } }] }],
      },
      {},
      LOL_ORDER,
      teamN,
    );
    const [capitalised] = variant.teams[0].seats;
    const [plain] = variant.teams[1].seats;
    expect(capitalised).toMatchObject({ role: "top", rating: 2150, openRating: 2050, subRole: "roamer", offRole: false });
    expect(plain).toMatchObject({ role: "top", rating: 1900, openRating: 1800, subRole: "split", offRole: false });
  });
});

describe("lineup captains", () => {
  it("crowns the seat the lineup names per team, and nobody on a team without one", () => {
    const [variant] = parseVariants({
      players: { "7": { name: "karin" }, "8": { name: "Tolgrn" }, "9": { name: "Egor" } },
      variants: [
        {
          teams: [
            { captain_member_id: 8, roster: { Tank: ["7"], Damage: ["8"] } },
            { roster: { Support: ["9"] } },
          ],
        },
      ],
    });
    expect(variant.teams.map((team) => team.captainUuid)).toEqual(["8", null]);
    expect(variant.teams[0].seats.map((seat) => [seat.name, seat.isCaptain])).toEqual([
      ["karin", false],
      ["Tolgrn", true],
    ]);
    expect(variant.teams[1].seats[0].isCaptain).toBe(false);
  });
});

describe("lobbyCandidateCount", () => {
  it("counts who a lobby can seat: in the lineup, present, not on another lobby's floor or pin", () => {
    const rows = [
      row({ workspace_member_id: 1 }),
      row({ workspace_member_id: 2, current_lobby: 1 }),
      row({ workspace_member_id: 3, current_lobby: 0 }),
      row({ workspace_member_id: 4, lobby_pin: 0 }),
      row({ workspace_member_id: 5, away: true }),
      row({ workspace_member_id: 6, participation: "benched" }),
    ];
    expect(lobbyCandidateCount(rows, 1)).toBe(2);
  });
});

describe("waitingQueuePosition", () => {
  it("lines the waiting players up by how long each has sat out, then by games played", () => {
    const rows = [
      row({ id: 1, workspace_member_id: 7, sort_order: 0 }),
      row({ id: 2, workspace_member_id: 8, sort_order: 1 }),
      row({ id: 3, workspace_member_id: 9, sort_order: 2, current_lobby: 0 }),
      row({ id: 4, workspace_member_id: 10, sort_order: 3 }),
    ];
    const rotation = [
      hint({ workspace_member_id: 8, consecutive_sat: 2 }),
      hint({ workspace_member_id: 10, consecutive_sat: 2, games_played: 1 }),
      hint({ workspace_member_id: 7, games_played: 3 }),
    ];
    expect([7, 8, 9, 10].map((id) => waitingQueuePosition(rows, rotation, id))).toEqual([3, 1, null, 2]);
  });

  it("puts the host's must-play pin first, even with no sit-out behind it", () => {
    const rows = [
      row({ id: 1, workspace_member_id: 7, sort_order: 0 }),
      row({ id: 2, workspace_member_id: 8, sort_order: 1, participation: "must_play" }),
    ];
    const rotation = [
      hint({ workspace_member_id: 7, consecutive_sat: 1, games_played: 1 }),
      hint({ workspace_member_id: 8, consecutive_played: 2, games_played: 4 }),
    ];
    expect([7, 8].map((id) => waitingQueuePosition(rows, rotation, id))).toEqual([2, 1]);
  });

  it("breaks an equal sit-out by the shorter playing streak before total games", () => {
    const rows = [
      row({ id: 1, workspace_member_id: 7, sort_order: 0 }),
      row({ id: 2, workspace_member_id: 8, sort_order: 1 }),
    ];
    const rotation = [
      hint({ workspace_member_id: 7, consecutive_played: 3, games_played: 3 }),
      hint({ workspace_member_id: 8, consecutive_played: 1, games_played: 5 }),
    ];
    expect([7, 8].map((id) => waitingQueuePosition(rows, rotation, id))).toEqual([2, 1]);
  });
});

describe("myLobbyTeam", () => {
  it("finds the player's own team in the lobby whose shown option seats them", () => {
    const game = {
      settings: { points_per_win: 0, team_names: { "2": "Owls" }, workspace_discord_channel_id: null },
      lobbies: [
        {
          lobby_index: 0,
          selected_variant_index: 0,
          next_map_id: null,
          balance_result: { players: { "7": { name: "karin" } }, variants: [{ teams: [{ roster: { Tank: ["7"] } }] }] },
        },
        {
          lobby_index: 1,
          selected_variant_index: 1,
          next_map_id: 42,
          balance_result: {
            players: { "8": { name: "Tolgrn" }, "9": { name: "Egor" } },
            variants: [{ teams: [] }, { teams: [{ captain_member_id: 9, roster: { Tank: ["9"], Damage: ["8"] } }] }],
          },
        },
      ],
    } as unknown as CustomGame;

    expect(myLobbyTeam(game, 8, OW_ORDER, teamN)).toEqual({
      lobbyIndex: 1,
      teamName: "Owls",
      nextMapId: 42,
      members: [
        { uuid: "9", name: "Egor", role: "tank", isCaptain: true, isMe: false },
        { uuid: "8", name: "Tolgrn", role: "damage", isCaptain: false, isMe: true },
      ],
    });
    expect(myLobbyTeam(game, 99, OW_ORDER, teamN)).toBeNull();
  });
});

describe("isMixHost", () => {
  const closed = { host_user_id: 1, co_hosts: [{ user_id: 2 }], status: "completed" } as unknown as CustomGame;

  it("counts the host, a co-host and a superuser, and nobody else", () => {
    expect(isMixHost(closed, 1, false)).toBe(true);
    expect(isMixHost(closed, 2, false)).toBe(true);
    expect(isMixHost(closed, 3, true)).toBe(true);
    expect(isMixHost(closed, 3, false)).toBe(false);
    expect(isMixHost(closed, null, false)).toBe(false);
    expect(isMixHost(undefined, 1, true)).toBe(false);
  });

  it("ignores the mix's status, which canWriteMix does not: a closed mix still takes logs", () => {
    expect(isMixHost(closed, 1, false)).toBe(true);
    expect(canWriteMix(closed, 1, false)).toBe(false);
  });
});
