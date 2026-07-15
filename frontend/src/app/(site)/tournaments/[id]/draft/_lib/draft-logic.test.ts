import { describe, expect, it } from "vitest";

import type { RealtimeEventEnvelope } from "@/types/realtime.types";
import type { DraftBoard, DraftEventData, DraftPick, DraftPlayer, DraftTeam } from "@/types/draft.types";

import {
  applyDraftEvent,
  canConfirmPick,
  computeGating,
  draftInvalidationTargets,
  isUrgent,
  presenceFromEvent,
  remainingMs
} from "./draft-logic";

function team(
  id: number,
  captainUserId: number | null,
  pos: number,
  captainAuthUserId: number | null = null
): DraftTeam {
  return {
    id,
    session_id: 1,
    captain_user_id: captainUserId,
    captain_auth_user_id: captainAuthUserId,
    name: `T${id}`,
    draft_position: pos,
    exported_team_id: null,
  };
}

function player(id: number): DraftPlayer {
  return {
    id,
    session_id: 1,
    user_id: id,
    battle_tag: `P${id}`,
    primary_role: "dps",
    sub_role: null,
    is_flex: false,
    division_number: null,
    rank_value: 3000,
    status: "available",
    is_captain: false,
    drafted_by_team_id: null,
    secondary_roles_json: null,
    role_ranks: {},
    role_top_heroes: {},
    additional_info: {},
    version: 0,
  };
}

function pick(id: number, teamId: number, status: DraftPick["status"]): DraftPick {
  return {
    id,
    session_id: 1,
    overall_no: id,
    round_no: 1,
    pick_in_round: id,
    draft_team_id: teamId,
    target_role: null,
    target_rank_value: null,
    status,
    picked_player_id: null,
    picked_by_user_id: null,
    is_autopick: false,
    is_admin_override: false,
    clock_started_at: null,
    clock_expires_at: null,
    version: 0,
  };
}

function makeBoard(): DraftBoard {
  const p1 = pick(1, 10, "on_clock");
  return {
    session: {
      id: 1,
      tournament_id: 5,
      workspace_id: 2,
      status: "live",
      format: "snake",
      rounds: 2,
      pick_time_seconds: 45,
      team_size: 3,
      current_pick_id: 1,
      pool_source: "manual",
      source_balance_id: null,
      autopick_strategy: "best_fit",
      allow_admin_override: true,
      exported_at: null,
      export_status: null,
      settings_json: {},
      version: 0,
    },
    teams: [team(10, 100, 1), team(11, 101, 2)],
    picks: [p1, pick(2, 11, "upcoming")],
    players: [player(50), player(51)],
    current_pick: p1,
    server_time: "2026-06-05T00:00:00Z",
    last_event_id: 0,
  };
}

function ev(type: string, data: Partial<DraftEventData>): RealtimeEventEnvelope<DraftEventData> {
  return {
    event_id: 1,
    event_type: type,
    schema_version: 1,
    occurred_at: "2026-06-05T00:00:00Z",
    actor_user_id: null,
    data: { session_id: 1, ...data },
  };
}

describe("clock math", () => {
  it("remainingMs clamps at zero and parses ISO", () => {
    const now = Date.parse("2026-06-05T00:00:00Z");
    expect(remainingMs("2026-06-05T00:00:30Z", now)).toBe(30_000);
    expect(remainingMs("2026-06-04T23:59:59Z", now)).toBe(0);
    expect(remainingMs(null, now)).toBe(0);
  });

  it("isUrgent under 10s only", () => {
    expect(isUrgent(9_000)).toBe(true);
    expect(isUrgent(10_001)).toBe(false);
    expect(isUrgent(0)).toBe(false);
  });
});

describe("applyDraftEvent", () => {
  it("pick_made marks the pick + rosters the player", () => {
    const next = applyDraftEvent(
      makeBoard(),
      ev("draft.pick_made", { pick_id: 1, draft_team_id: 10, picked_player_id: 50 })
    );
    expect(next.picks.find((p) => p.id === 1)!.status).toBe("completed");
    const picked = next.players.find((p) => p.id === 50)!;
    expect(picked.status).toBe("picked");
    expect(picked.drafted_by_team_id).toBe(10);
    expect(next.players.filter((p) => p.status === "available").map((p) => p.id)).toEqual([51]);
  });

  it("autopicked marks is_autopick", () => {
    const next = applyDraftEvent(
      makeBoard(),
      ev("draft.autopicked", { pick_id: 1, picked_player_id: 50 })
    );
    const p = next.picks.find((x) => x.id === 1)!;
    expect(p.status).toBe("autopicked");
    expect(p.is_autopick).toBe(true);
  });

  it("pick_started advances current pick + clock", () => {
    const next = applyDraftEvent(
      makeBoard(),
      ev("draft.pick_started", { pick_id: 2, clock_expires_at: "2026-06-05T00:01:00Z" })
    );
    expect(next.session.current_pick_id).toBe(2);
    expect(next.current_pick!.id).toBe(2);
    expect(next.current_pick!.clock_expires_at).toBe("2026-06-05T00:01:00Z");
  });

  it("paused/resumed/completed/cancelled set session status", () => {
    expect(applyDraftEvent(makeBoard(), ev("draft.paused", {})).session.status).toBe("paused");
    expect(applyDraftEvent(makeBoard(), ev("draft.resumed", {})).session.status).toBe("live");
    const done = applyDraftEvent(makeBoard(), ev("draft.completed", {}));
    expect(done.session.status).toBe("completed");
    expect(done.current_pick).toBeNull();
    expect(applyDraftEvent(makeBoard(), ev("draft.cancelled", {})).session.status).toBe("cancelled");
  });

  it("presence does not mutate the board", () => {
    const board = makeBoard();
    expect(applyDraftEvent(board, ev("draft.presence", { count_bucket: "50+" }))).toBe(board);
  });

  it("is idempotent for pick_made", () => {
    const e = ev("draft.pick_made", { pick_id: 1, draft_team_id: 10, picked_player_id: 50 });
    const once = applyDraftEvent(makeBoard(), e);
    const twice = applyDraftEvent(once, e);
    expect(twice.picks.find((p) => p.id === 1)!.status).toBe("completed");
    expect(twice.players.find((p) => p.id === 50)!.status).toBe("picked");
  });

  it("does not mutate the input board", () => {
    const board = makeBoard();
    applyDraftEvent(board, ev("draft.pick_made", { pick_id: 1, picked_player_id: 50 }));
    expect(board.picks.find((p) => p.id === 1)!.status).toBe("on_clock");
    expect(board.players.every((p) => p.status === "available")).toBe(true);
  });
});

describe("computeGating", () => {
  it("captain on the clock (by linked player id)", () => {
    const g = computeGating(makeBoard(), [100], null, false);
    expect(g.isCaptain).toBe(true);
    expect(g.myTeamId).toBe(10);
    expect(g.isMyPick).toBe(true);
    expect(g.isSpectator).toBe(false);
  });

  it("captain matched by auth user id (no linked player)", () => {
    // team 10 captain_auth_user_id = 555, no player linkage
    const board = makeBoard();
    board.teams = [team(10, null, 1, 555), team(11, null, 2, 666)];
    const g = computeGating(board, [], 555, false);
    expect(g.isCaptain).toBe(true);
    expect(g.myTeamId).toBe(10);
    expect(g.isMyPick).toBe(true);
  });

  it("captain not on the clock", () => {
    const g = computeGating(makeBoard(), [101], null, false);
    expect(g.isCaptain).toBe(true);
    expect(g.isMyPick).toBe(false);
  });

  it("anonymous spectator", () => {
    const g = computeGating(makeBoard(), [], null, false);
    expect(g.isSpectator).toBe(true);
    expect(g.isMyPick).toBe(false);
  });

  it("admin is not a spectator and not my-pick", () => {
    const g = computeGating(makeBoard(), [999], null, true);
    expect(g.isAdmin).toBe(true);
    expect(g.isSpectator).toBe(false);
    expect(g.isMyPick).toBe(false);
  });
});

describe("draft safety state", () => {
  it("applies resolved role, rank, and authoritative pick version", () => {
    const next = applyDraftEvent(
      makeBoard(),
      ev("draft.pick_made", {
        pick_id: 1,
        picked_player_id: 50,
        target_role: "support",
        target_rank_value: 2875,
        pick_version: 4
      })
    );

    const resolved = next.picks.find((p) => p.id === 1)!;
    expect(resolved.target_role).toBe("support");
    expect(resolved.target_rank_value).toBe(2875);
    expect(resolved.version).toBe(4);
  });

  it("pauses on blocked while keeping the current pick unresolved", () => {
    const next = applyDraftEvent(makeBoard(), ev("draft.blocked", { reason: "role_shortage" }));

    expect(next.session.status).toBe("paused");
    expect(next.session.blocked_reason).toBe("role_shortage");
    expect(next.current_pick?.status).toBe("on_clock");
  });

  it("builds real presence from authenticated IDs and anonymous count", () => {
    expect(
      presenceFromEvent(
        { session_id: 1, user_ids: [7, 9], anonymous_viewer_count: 3 },
        "2026-07-14T12:00:00Z"
      )
    ).toEqual({
      users: {
        7: { last_active_at: "2026-07-14T12:00:00Z" },
        9: { last_active_at: "2026-07-14T12:00:00Z" }
      },
      anonymous_viewer_count: 3
    });
  });

  it("allows confirm only while connected with current safe options", () => {
    const options = {
      pick_id: 1,
      pick_version: 4,
      draft_team_id: 10,
      options: [
        {
          player_id: 50,
          role: "support" as const,
          is_safe: true,
          reason_code: null,
          unmatched_slots: [],
          blocking_player_ids: [],
          suggestion_score: null
        }
      ]
    };

    expect(canConfirmPick("connected", 4, options, { playerId: 50, role: "support" })).toBe(true);
    expect(canConfirmPick("reconnecting", 4, options, { playerId: 50, role: "support" })).toBe(false);
    expect(canConfirmPick("connected", 5, options, { playerId: 50, role: "support" })).toBe(false);
  });

  it("returns narrow invalidation targets for realtime changes", () => {
    expect(draftInvalidationTargets("draft.pick_made")).toEqual(["feasibility", "options"]);
    expect(draftInvalidationTargets("draft.player_updated")).toEqual([
      "board",
      "feasibility",
      "options"
    ]);
    expect(draftInvalidationTargets("draft.presence")).toEqual([]);
  });
});
