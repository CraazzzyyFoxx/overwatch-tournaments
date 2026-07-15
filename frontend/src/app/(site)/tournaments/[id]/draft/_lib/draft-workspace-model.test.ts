import { describe, expect, it } from "vitest";

import type { DraftPickOptionsResponse, DraftPick, DraftPlayer } from "@/types/draft.types";

import {
  buildDraftEventFeed,
  buildRosterByTeam,
  filterDraftPlayers,
  normalizeTopHeroes,
  roleTopHeroes,
  groupPicksByRound,
  rosterRoleForPlayer,
  rosterRankForPlayer,
  optionForSelection,
  playerRoles,
  parseDraftViewParams
} from "./draft-workspace-model";

const players = [
  { id: 1, battle_tag: "Zeta#1", primary_role: "support", secondary_roles_json: [], rank_value: 2700 },
  { id: 2, battle_tag: "Alpha#2", primary_role: "tank", secondary_roles_json: ["dps"], rank_value: 3100 }
] as DraftPlayer[];

describe("draft workspace model", () => {
  it("only resolves an exact server-approved player and role option", () => {
    const response: DraftPickOptionsResponse = {
      pick_id: 9,
      pick_version: 3,
      draft_team_id: 5,
      options: [
        { player_id: 2, role: "tank", is_safe: true, reason_code: null, unmatched_slots: [], blocking_player_ids: [], suggestion_score: 2 },
        { player_id: 2, role: "dps", is_safe: false, reason_code: "role_shortage", unmatched_slots: [], blocking_player_ids: [1], suggestion_score: null }
      ]
    };
    expect(optionForSelection(response, 2, "tank")?.is_safe).toBe(true);
    expect(optionForSelection(response, 2, "dps")?.reason_code).toBe("role_shortage");
    expect(optionForSelection(response, 1, "support")).toBeNull();
  });

  it("filters and sorts the public pool with URL-safe values", () => {
    expect(filterDraftPlayers(players, { role: "all", sort: "name", query: "a" }).map((player) => player.id)).toEqual([2, 1]);
    expect(filterDraftPlayers(players, { role: "dps", sort: "rank", query: "" }).map((player) => player.id)).toEqual([2]);
    expect(parseDraftViewParams(new URLSearchParams("role=oops&sort=name&view=team&q=abc"))).toEqual({
      role: "all",
      sort: "name",
      view: "team",
      query: "abc"
    });
  });

  it("builds a public event feed only from resolved picks", () => {
    const feed = buildDraftEventFeed(
      [
        { id: 1, overall_no: 1, status: "completed", draft_team_id: 5, picked_player_id: 2, target_role: "tank", is_autopick: false },
        { id: 2, overall_no: 2, status: "upcoming", draft_team_id: 6, picked_player_id: null, target_role: null, is_autopick: false }
      ] as never,
      new Map([[5, "Alpha"]]),
      new Map([[2, "Player#2"]])
    );
    expect(feed).toEqual([{ pickId: 1, overallNo: 1, teamName: "Alpha", playerName: "Player#2", role: "tank", autopick: false }]);
  });

  it("derives role choices and rosters from the public board snapshot", () => {
    expect(playerRoles(players[1])).toEqual(["tank", "dps"]);
    const rosters = buildRosterByTeam([
      { ...players[0], status: "picked", drafted_by_team_id: 5 },
      { ...players[1], status: "available", drafted_by_team_id: null }
    ] as DraftPlayer[]);
    expect(rosters.get(5)?.map((entry) => entry.id)).toEqual([1]);
    expect(rosters.has(0)).toBe(false);
  });
});

const mkPlayer = (p: Partial<DraftPlayer>): DraftPlayer => ({
  id: 1, session_id: 1, user_id: null, battle_tag: "Ana#1", primary_role: "support",
  sub_role: null, is_flex: false, division_number: null, rank_value: 3000,
  status: "available", is_captain: false, drafted_by_team_id: null,
  secondary_roles_json: null, role_ranks: {}, role_top_heroes: {}, additional_info: {},
  version: 1, ...p,
});

describe("extended filterDraftPlayers search", () => {
  it("matches on sub_role", () => {
    const players = [mkPlayer({ id: 1, battle_tag: "Zed", sub_role: "hitscan" }), mkPlayer({ id: 2, battle_tag: "Boo", sub_role: "flex" })];
    const out = filterDraftPlayers(players, { role: "all", sort: "rank", query: "hitscan" });
    expect(out.map((p) => p.id)).toEqual([1]);
  });
  it("matches on role label", () => {
    const players = [mkPlayer({ id: 1, primary_role: "tank" }), mkPlayer({ id: 2, primary_role: "support" })];
    const out = filterDraftPlayers(players, { role: "all", sort: "rank", query: "tank" });
    expect(out.map((p) => p.id)).toEqual([1]);
  });
});

describe("normalizeTopHeroes", () => {
  it("normalizes string + object entries", () => {
    expect(normalizeTopHeroes(["ana", { slug: "kiriko", image_path: "/k.png" }])).toEqual([
      { slug: "ana", imagePath: null },
      { slug: "kiriko", imagePath: "/k.png" },
    ]);
  });
  it("handles undefined", () => {
    expect(normalizeTopHeroes(undefined)).toEqual([]);
  });
});

describe("groupPicksByRound", () => {
  it("groups and sorts by round then pick_in_round", () => {
    const picks = [
      { id: 3, round_no: 2, pick_in_round: 1, overall_no: 3 },
      { id: 1, round_no: 1, pick_in_round: 1, overall_no: 1 },
      { id: 2, round_no: 1, pick_in_round: 2, overall_no: 2 },
    ] as DraftPick[];
    const groups = groupPicksByRound(picks);
    expect(groups.map((g) => g.round)).toEqual([1, 2]);
    expect(groups[0].picks.map((p) => p.id)).toEqual([1, 2]);
  });
});

describe("roster role/rank", () => {
  it("uses drafted target role over primary", () => {
    const player = mkPlayer({ id: 5, primary_role: "support", role_ranks: { dps: 3500, support: 3000 } });
    const picks = [{ id: 9, picked_player_id: 5, target_role: "dps" }] as DraftPick[];
    expect(rosterRoleForPlayer(player, picks)).toBe("dps");
    expect(rosterRankForPlayer(player, "dps")).toBe(3500);
  });
  it("falls back to primary role + rank_value", () => {
    const player = mkPlayer({ id: 6, primary_role: "tank", rank_value: 2800, role_ranks: {} });
    expect(rosterRoleForPlayer(player, [])).toBe("tank");
    expect(rosterRankForPlayer(player, "tank")).toBe(2800);
  });
});
