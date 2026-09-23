import { describe, expect, it } from "vitest";

import type { DraftPickOptionsResponse, DraftPick, DraftPlayer } from "@/types/draft.types";

import {
  buildRosterByTeam,
  draftPoolView,
  filterDraftPlayers,
  normalizeTopHeroes,
  groupPicksByRound,
  rosterRoleForPlayer,
  slotRankForPlayer,
  optionForSelection,
  playerRoles,
  parseDraftViewParams
} from "./workspace-model";

const players = [
  { id: 1, battle_tag: "Zeta#1", primary_role: "support", secondary_roles: [], effective_rank: 2700 },
  { id: 2, battle_tag: "Alpha#2", primary_role: "tank", secondary_roles: ["damage"], effective_rank: 3100 }
] as DraftPlayer[];

describe("draft workspace model", () => {
  it("only resolves an exact server-approved player and role option", () => {
    const response: DraftPickOptionsResponse = {
      pick_id: 9,
      pick_version: 3,
      draft_team_id: 5,
      options: [
        { player_id: 2, role: "tank", is_safe: true, reason_code: null, unmatched_slots: [], blocking_player_ids: [], suggestion_score: 2 },
        { player_id: 2, role: "damage", is_safe: false, reason_code: "role_shortage", unmatched_slots: [], blocking_player_ids: [1], suggestion_score: null }
      ]
    };
    expect(optionForSelection(response, 2, "tank")?.is_safe).toBe(true);
    expect(optionForSelection(response, 2, "damage")?.reason_code).toBe("role_shortage");
    expect(optionForSelection(response, 1, "support")).toBeNull();
  });

  it("filters and sorts the public pool with URL-safe values", () => {
    expect(filterDraftPlayers(players, { role: "all", sort: "name", query: "a" }).map((player) => player.id)).toEqual([2, 1]);
    expect(filterDraftPlayers(players, { role: "damage", sort: "rank", query: "" }).map((player) => player.id)).toEqual([2]);
    expect(parseDraftViewParams(new URLSearchParams("role=oops&sort=name&view=team&pool=drafted&q=abc"))).toEqual({
      role: "all",
      sort: "name",
      view: "team",
      pool: "drafted",
      query: "abc"
    });
    // An unknown pool name falls back to the one everybody starts on.
    expect(parseDraftViewParams(new URLSearchParams("pool=oops")).pool).toBe("available");
  });

  it("derives role choices and rosters from the public board snapshot", () => {
    expect(playerRoles(players[1])).toEqual(["tank", "damage"]);
    const rosters = buildRosterByTeam([
      { ...players[0], status: "picked", drafted_by_team_id: 5 },
      { ...players[1], status: "available", drafted_by_team_id: null }
    ] as DraftPlayer[]);
    expect(rosters.get(5)?.map((entry) => entry.id)).toEqual([1]);
    expect(rosters.has(0)).toBe(false);
  });

  it("splits the board into the three lists the pool column can show", () => {
    const pool = [
      { ...players[0], id: 1, status: "available" },
      { ...players[1], id: 2, status: "picked", drafted_by_team_id: 5 }
    ] as DraftPlayer[];
    const base = { role: "all", sort: "rank", query: "" } as const;

    const available = draftPoolView(pool, { ...base, pool: "available" }, new Set([1]));
    expect(available.filtered.map((entry) => entry.id)).toEqual([1]);
    expect(available.drafted.map((entry) => entry.id)).toEqual([2]);
    // The role chips keep counting who is LEFT whichever tab is open.
    expect(available.roleCounts.support).toBe(1);
    expect(available.roleCounts.tank).toBe(0);

    expect(draftPoolView(pool, { ...base, pool: "drafted" }, new Set([1])).filtered.map((e) => e.id)).toEqual([2]);
    expect(draftPoolView(pool, { ...base, pool: "shortlist" }, new Set([1])).filtered.map((e) => e.id)).toEqual([1]);
    // A shortlisted player who got drafted drops out of the shortlist tab.
    expect(draftPoolView(pool, { ...base, pool: "shortlist" }, new Set([2])).filtered).toEqual([]);
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
      id: 3, primary_role: "damage", secondary_roles: ["tank"], is_flex: true,
      role_ranks: { damage: 3200, tank: 3000 },
    });
    expect(playerRoles(flex)).toEqual(["damage", "tank"]);
    expect(filterDraftPlayers([flex], { role: "support", sort: "rank", query: "" })).toEqual([]);
    const fullFlex = mkPlayer({
      id: 5, primary_role: "damage", secondary_roles: ["tank", "support"], is_flex: true,
      role_ranks: { damage: 3200, tank: 3000, support: 2900 },
    });
    expect(playerRoles(fullFlex)).toEqual(["damage", "tank", "support"]);
    // Not flex: still exactly what was declared.
    const strict = mkPlayer({ id: 4, primary_role: "damage", secondary_roles: ["tank"] });
    expect(playerRoles(strict)).toEqual(["damage", "tank"]);
    expect(filterDraftPlayers([strict], { role: "support", sort: "rank", query: "" })).toEqual([]);
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
    const player = mkPlayer({ id: 5, primary_role: "support", role_ranks: { damage: 3500, support: 3000 } });
    const picks = [{ id: 9, picked_player_id: 5, target_role: "damage" }] as DraftPick[];
    expect(rosterRoleForPlayer(player, picks)).toBe("damage");
    expect(slotRankForPlayer(player, "damage", ROLE_SLOTS)).toBe(3500);
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
      role_ranks: { damage: 3500, support: 3000 },
      effective_rank: 3500
    });
    expect(slotRankForPlayer(player, null, ROLE_SLOTS)).toBe(3500);
  });
  it("shows the server's effective rank under an all-flex shape", () => {
    const player = mkPlayer({
      id: 7,
      primary_role: "support",
      role_ranks: { damage: 3500, support: 3000 },
      effective_rank: 3500
    });
    expect(slotRankForPlayer(player, "support", ALL_FLEX)).toBe(3500);
    expect(slotRankForPlayer(player, "support", ROLE_SLOTS)).toBe(3000);
  });
});
