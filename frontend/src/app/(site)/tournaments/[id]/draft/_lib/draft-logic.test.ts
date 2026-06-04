import { describe, expect, it } from "vitest";

import type { RealtimeEventEnvelope } from "@/types/realtime.types";
import type { DraftBoard, DraftEventData, DraftPick, DraftPlayer, DraftTeam } from "@/types/draft.types";

import { applyDraftEvent, computeGating, isUrgent, remainingMs } from "./draft-logic";

function team(id: number, captainUserId: number | null, pos: number): DraftTeam {
  return {
    id,
    session_id: 1,
    captain_user_id: captainUserId,
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
    anomaly_flags: {},
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
  it("captain on the clock", () => {
    const g = computeGating(makeBoard(), [100], false);
    expect(g.isCaptain).toBe(true);
    expect(g.myTeamId).toBe(10);
    expect(g.isMyPick).toBe(true);
    expect(g.isSpectator).toBe(false);
  });

  it("captain not on the clock", () => {
    const g = computeGating(makeBoard(), [101], false);
    expect(g.isCaptain).toBe(true);
    expect(g.isMyPick).toBe(false);
  });

  it("anonymous spectator", () => {
    const g = computeGating(makeBoard(), [], false);
    expect(g.isSpectator).toBe(true);
    expect(g.isMyPick).toBe(false);
  });

  it("admin is not a spectator and not my-pick", () => {
    const g = computeGating(makeBoard(), [999], true);
    expect(g.isAdmin).toBe(true);
    expect(g.isSpectator).toBe(false);
    expect(g.isMyPick).toBe(false);
  });
});
