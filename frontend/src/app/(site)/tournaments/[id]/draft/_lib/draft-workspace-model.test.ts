import { describe, expect, it } from "vitest";

import type { DraftPickOptionsResponse, DraftPlayer } from "@/types/draft.types";

import {
  buildDraftEventFeed,
  buildRosterByTeam,
  filterDraftPlayers,
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
