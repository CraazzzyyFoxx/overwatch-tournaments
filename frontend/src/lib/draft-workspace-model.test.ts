import { describe, expect, it } from "vitest";

import type { DraftPickOption, DraftPickOptionsResponse, DraftPick, DraftPlayer, DraftRole } from "@/types/draft.types";

import {
  buildRosterByTeam,
  filterDraftPlayers,
  normalizeTopHeroes,
  groupPicksByRound,
  rosterRoleForPlayer,
  slotRankForPlayer,
  optionForSelection,
  safeRoleForPlayer,
  playerRoles,
  parseDraftViewParams
} from "./draft-workspace-model";

const players = [
  { id: 1, battle_tag: "Zeta#1", primary_role: "support", secondary_roles: [], effective_rank: 2700 },
  { id: 2, battle_tag: "Alpha#2", primary_role: "tank", secondary_roles: ["dps"], effective_rank: 3100 }
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
  id: 1, session_id: 1, registration_id: 10, user_id: null, battle_tag: "Ana#1",
  primary_role: "support", sub_role: null, is_flex: false, effective_rank: 3000,
  status: "available", is_captain: false, drafted_by_team_id: null,
  secondary_roles: [], role_ranks: {}, role_sources: {}, role_top_heroes: {}, notes: null,
  custom_fields: [], version: 1, ...p,
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
  it("offers a flex player only the roles the server says are playable", () => {
    // `is_flex` is never consulted server-side: a pick is validated through
    // `PlayerRoster.covers(role)`, so offering an unranked role only produced a
    // pick the server rejected. A flex player ranked on all three still gets
    // all three, because all three land in primary + secondary_roles.
    const flex = mkPlayer({
      id: 3, primary_role: "dps", secondary_roles: ["tank"], is_flex: true,
      role_ranks: { dps: 3200, tank: 3000 },
    });
    expect(playerRoles(flex)).toEqual(["dps", "tank"]);
    expect(filterDraftPlayers([flex], { role: "support", sort: "rank", query: "" })).toEqual([]);
    const fullFlex = mkPlayer({
      id: 5, primary_role: "dps", secondary_roles: ["tank", "support"], is_flex: true,
      role_ranks: { dps: 3200, tank: 3000, support: 2900 },
    });
    expect(playerRoles(fullFlex)).toEqual(["dps", "tank", "support"]);
    // Not flex: still exactly what was declared.
    const strict = mkPlayer({ id: 4, primary_role: "dps", secondary_roles: ["tank"] });
    expect(playerRoles(strict)).toEqual(["dps", "tank"]);
    expect(filterDraftPlayers([strict], { role: "support", sort: "rank", query: "" })).toEqual([]);
  });
  it("preselects the primary role when it is safe, not the server's first safe option", () => {
    // The server emits options in tank, dps, support order, so a support main
    // who also plays tank used to open on tank.
    const player = mkPlayer({ id: 5, primary_role: "support", secondary_roles: ["tank"] });
    const option = (role: DraftRole, is_safe: boolean): DraftPickOption => ({
      player_id: 5, role, is_safe, reason_code: is_safe ? null : "role_shortage",
      unmatched_slots: [], blocking_player_ids: [], suggestion_score: null
    });
    const response = (options: DraftPickOption[]): DraftPickOptionsResponse => ({
      pick_id: 1, pick_version: 0, draft_team_id: 2, options
    });

    expect(safeRoleForPlayer(response([option("tank", true), option("support", true)]), player)).toBe("support");
    // Primary blocked: fall to the next declared role rather than to nothing.
    expect(safeRoleForPlayer(response([option("tank", true), option("support", false)]), player)).toBe("tank");
    expect(safeRoleForPlayer(response([option("tank", false), option("support", false)]), player)).toBeNull();
    expect(safeRoleForPlayer(null, player)).toBeNull();
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

const ROLE_SLOTS = { has_role_slots: true };
const ALL_FLEX = { has_role_slots: false };

describe("roster role/rank", () => {
  it("uses drafted target role over primary", () => {
    const player = mkPlayer({ id: 5, primary_role: "support", role_ranks: { dps: 3500, support: 3000 } });
    const picks = [{ id: 9, picked_player_id: 5, target_role: "dps" }] as DraftPick[];
    expect(rosterRoleForPlayer(player, picks)).toBe("dps");
    expect(slotRankForPlayer(player, "dps", ROLE_SLOTS)).toBe(3500);
  });
  it("falls back to the primary role and that role's own rank", () => {
    const player = mkPlayer({ id: 6, primary_role: "tank", role_ranks: { tank: 2800 } });
    expect(rosterRoleForPlayer(player, [])).toBe("tank");
    expect(slotRankForPlayer(player, "tank", ROLE_SLOTS)).toBe(2800);
  });
  it("reports no role and no rank once every role lost its rank", () => {
    // An organizer can strip the ranks mid-draft; nothing may stand in.
    const player = mkPlayer({ id: 8, primary_role: null, secondary_roles: [], role_ranks: {} });
    expect(rosterRoleForPlayer(player, [])).toBe(null);
    expect(slotRankForPlayer(player, null, ROLE_SLOTS)).toBe(null);
    expect(playerRoles(player)).toEqual([]);
  });
  it("uses effective_rank for a pool card on a role-slotted board", () => {
    const player = mkPlayer({
      id: 9,
      primary_role: "support",
      role_ranks: { dps: 3500, support: 3000 },
      effective_rank: 3500
    });
    expect(slotRankForPlayer(player, null, ROLE_SLOTS)).toBe(3500);
  });
  it("shows the server's effective rank under an all-flex shape", () => {
    const player = mkPlayer({
      id: 7,
      primary_role: "support",
      role_ranks: { dps: 3500, support: 3000 },
      effective_rank: 3500
    });
    expect(slotRankForPlayer(player, "support", ALL_FLEX)).toBe(3500);
    expect(slotRankForPlayer(player, "support", ROLE_SLOTS)).toBe(3000);
  });
});
