import { describe, expect, it } from "vitest";

import type { DraftBoard, DraftPick, DraftPlayer, DraftTeam } from "@/types/draft.types";
import type { RosterShape } from "@/lib/roster/shape";

import type { DraftGating } from "./logic";
import {
  actingTeamId,
  bestSeatRole,
  buildTeamViews,
  fitByPlayer,
  poolRoleColumns,
  roleMarket,
  roundDirection
} from "./room-model";

const shape = (slots: RosterShape["slots"]): RosterShape => {
  const size = Object.values(slots).reduce((sum, count) => sum + (count ?? 0), 0);
  const flex = slots.flex ?? 0;
  return { slots, team_size: size, flex_slots: flex, has_role_slots: size > flex, draft_rounds: size - 1, source: null };
};

const player = (id: number, patch: Partial<DraftPlayer>): DraftPlayer => ({
  id, session_id: 1, registration_id: id, user_id: id, battle_tag: `P${id}`,
  primary_role: "damage", sub_role: null, is_flex: false, effective_rank: 3000,
  status: "available", is_captain: false, drafted_by_team_id: null,
  secondary_roles: [], role_ranks: { damage: 3000 }, role_sources: {}, role_top_heroes: {}, role_sub_roles: {},
  notes: null, custom_fields: [], version: 1, ...patch
});

const team = (id: number, position: number): DraftTeam => ({
  id, session_id: 1, captain_user_id: null, captain_auth_user_id: null, name: `T${id}`,
  draft_position: position, exported_team_id: null
});

const pick = (id: number, patch: Partial<DraftPick>): DraftPick => ({
  id, session_id: 1, overall_no: id, round_no: 1, pick_in_round: id, draft_team_id: 1,
  target_role: null, target_rank_value: null, status: "upcoming", picked_player_id: null,
  picked_by_user_id: null, is_autopick: false, is_admin_override: false, clock_started_at: null,
  clock_expires_at: null, overtime_started_at: null, version: 0, ...patch
});

const board = (patch: Partial<DraftBoard> & { shape: RosterShape }): DraftBoard => ({
  session: {
    id: 1, tournament_id: 1, workspace_id: 1, status: "live", blocked_reason: null, format: "snake",
    rounds: 4, pick_time_seconds: 45, overtime_seconds: 10, roster_shape: patch.shape, current_pick_id: null,
    pool_source: "manual", source_balance_id: null, autopick_strategy: "best_fit", allow_admin_override: true,
    exported_at: null, export_status: null, settings_json: {}, version: 1, created_at: null
  },
  teams: [team(1, 1), team(2, 2)],
  picks: [],
  players: [],
  current_pick: null,
  server_time: "2026-09-23T00:00:00Z",
  last_event_id: null,
  ...patch
});

const gating = (patch: Partial<DraftGating>): DraftGating => ({
  myTeamId: null, isCaptain: false, isAdmin: false, isMyPick: false, isSpectator: false, ...patch
});

describe("buildTeamViews", () => {
  it("seats a role's overflow into flex and flags a player drafted onto a role they never registered", () => {
    const b = board({
      shape: shape({ tank: 1, damage: 1, flex: 1 }),
      players: [
        player(1, { status: "picked", drafted_by_team_id: 1, is_captain: true }),
        player(2, { status: "picked", drafted_by_team_id: 1 }),
        player(3, { status: "picked", drafted_by_team_id: 1, primary_role: "support", role_ranks: { support: 2800 } })
      ],
      picks: [
        pick(1, { status: "completed", picked_player_id: 2, target_role: "damage" }),
        pick(2, { status: "completed", picked_player_id: 3, target_role: "tank" })
      ]
    });
    const cells = buildTeamViews(b).get(1)!.cells;
    // Captain takes the damage slot, the second damage main spills into flex,
    // the support main overridden onto tank sits there off-role.
    expect(cells.map((cell) => [cell.code, cell.player?.id ?? null, cell.offRole])).toEqual([
      ["tank", 3, true],
      ["damage", 1, false],
      ["flex", 2, false]
    ]);
    expect(buildTeamViews(b).get(1)!.full).toBe(true);
  });
});

describe("pool columns and seating", () => {
  it("shows only the roles the shape asks for, plus pool roles when a flex slot can seat them", () => {
    const players = [player(1, {}), player(2, { primary_role: "support", role_ranks: { support: 1 } })];
    expect(poolRoleColumns(shape({ tank: 1, damage: 2 }), players)).toEqual(["tank", "damage"]);
    expect(poolRoleColumns(shape({ flex: 6 }), players)).toEqual(["damage", "support"]);
  });

  it("picks the filtered role when seatable, else the best-ranked seatable one", () => {
    const b = board({ shape: shape({ tank: 1, support: 1 }) });
    const view = buildTeamViews(b).get(1)!;
    const flexy = player(9, {
      primary_role: "damage", secondary_roles: ["tank", "support"],
      role_ranks: { damage: 4000, tank: 3000, support: 3500 }
    });
    expect(bestSeatRole(flexy, view, "all")).toBe("support");
    expect(bestSeatRole(flexy, view, "tank")).toBe("tank");
    expect(bestSeatRole(player(10, {}), view, "all")).toBeNull();
  });
});

describe("roleMarket", () => {
  it("flags a deficit when mains plus flex players cannot fill the open slots", () => {
    const b = board({
      shape: shape({ tank: 1, damage: 1 }),
      players: [player(1, { primary_role: "tank", role_ranks: { tank: 1 } })]
    });
    const market = roleMarket(b, buildTeamViews(b));
    expect(market.map((entry) => [entry.role, entry.openSlots, entry.deficit])).toEqual([
      ["tank", 2, true],
      ["damage", 2, true]
    ]);
    expect(roleMarket(board({ shape: shape({ flex: 5 }) }), new Map())).toEqual([]);
  });
});

describe("actingTeamId", () => {
  const clockOn2 = board({ shape: shape({ tank: 1 }), current_pick: pick(1, { draft_team_id: 2, status: "on_clock" }) });

  it("keeps a captain on their own team, sends an admin to the clock, and lets a captain-admin choose", () => {
    expect(actingTeamId(clockOn2, gating({ isCaptain: true, myTeamId: 1 }), "clock")).toBe(1);
    expect(actingTeamId(clockOn2, gating({ isAdmin: true }), "mine")).toBe(2);
    expect(actingTeamId(clockOn2, gating({ isCaptain: true, isAdmin: true, myTeamId: 1 }), "mine")).toBe(1);
    expect(actingTeamId(clockOn2, gating({ isCaptain: true, isAdmin: true, myTeamId: 1 }), "clock")).toBe(2);
  });

  it("acts for nobody once the draft is over", () => {
    const done = { ...clockOn2, session: { ...clockOn2.session, status: "completed" as const } };
    expect(actingTeamId(done, gating({ isCaptain: true, myTeamId: 1 }), "mine")).toBeNull();
  });
});

describe("roundDirection", () => {
  it("reads the direction off the pick rows, not the format", () => {
    const b = board({
      shape: shape({ tank: 1 }),
      teams: [team(1, 1), team(2, 2), team(3, 3)],
      picks: [
        pick(1, { round_no: 1, pick_in_round: 1, draft_team_id: 1 }),
        pick(2, { round_no: 1, pick_in_round: 2, draft_team_id: 2 }),
        pick(3, { round_no: 2, pick_in_round: 1, draft_team_id: 3 }),
        pick(4, { round_no: 2, pick_in_round: 2, draft_team_id: 2 }),
        pick(5, { round_no: 3, pick_in_round: 1, draft_team_id: 2 }),
        pick(6, { round_no: 3, pick_in_round: 2, draft_team_id: 3 }),
        pick(7, { round_no: 3, pick_in_round: 3, draft_team_id: 1 })
      ]
    });
    expect([1, 2, 3].map((round) => roundDirection(b, round))).toEqual(["forward", "reverse", "custom"]);
  });
});

describe("fitByPlayer", () => {
  it("prefers the filtered role's score over a higher score on another role", () => {
    const scores = [
      { player_id: 1, role: "damage" as const, score: 90 },
      { player_id: 1, role: "tank" as const, score: 60 }
    ];
    expect(fitByPlayer(scores, "all").get(1)).toEqual({ role: "damage", score: 90 });
    expect(fitByPlayer(scores, "tank").get(1)).toEqual({ role: "tank", score: 60 });
  });
});
