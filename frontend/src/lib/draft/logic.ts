import type { RealtimeEventEnvelope } from "@/types/realtime.types";
import type { RealtimeConnectionState } from "@/types/realtime.types";
import type {
  DraftBoard,
  DraftEventData,
  DraftPick,
  DraftPickStatus,
  DraftPickOptionsResponse,
  DraftPresenceState,
  DraftRole,
} from "@/types/draft.types";

const URGENT_THRESHOLD_MS = 10_000;

/** Remaining clock in ms from an absolute ISO deadline. Clamped at 0. */
export function remainingMs(clockExpiresAt: string | null, nowMs: number): number {
  if (!clockExpiresAt) return 0;
  const expires = Date.parse(clockExpiresAt);
  if (Number.isNaN(expires)) return 0;
  return Math.max(0, expires - nowMs);
}

export function isUrgent(ms: number): boolean {
  return ms > 0 && ms <= URGENT_THRESHOLD_MS;
}

function setPick(
  board: DraftBoard,
  pickId: number,
  patch: Partial<DraftPick>
): DraftPick[] {
  return board.picks.map((p) => (p.id === pickId ? { ...p, ...patch } : p));
}

/**
 * Patch one pick and keep `current_pick` pointing at the SAME object when it is
 * that pick: the command bar reads the clock off `current_pick`, which is a
 * separate reference from the row in `picks`.
 */
function patchPick(board: DraftBoard, pickId: number, patch: Partial<DraftPick>): DraftBoard {
  const picks = setPick(board, pickId, patch);
  return {
    ...board,
    picks,
    current_pick:
      board.current_pick?.id === pickId
        ? picks.find((p) => p.id === pickId) ?? board.current_pick
        : board.current_pick,
  };
}

/**
 * Apply a realtime draft event to a board snapshot, immutably. Idempotent:
 * re-applying the same event converges to the same state.
 */
export function applyDraftEvent(
  board: DraftBoard,
  event: RealtimeEventEnvelope<DraftEventData>
): DraftBoard {
  const data = event.data;
  switch (event.event_type) {
    case "draft.presence":
      return board; // ephemeral; handled outside the board cache

    case "draft.session_updated":
      return data.status ? { ...board, session: { ...board.session, status: data.status } } : board;

    case "draft.pick_made":
    case "draft.autopicked": {
      if (data.pick_id == null) return board;
      const status: DraftPickStatus =
        event.event_type === "draft.autopicked" ? "autopicked" : "completed";
      const picks = setPick(board, data.pick_id, {
        status,
        picked_player_id: data.picked_player_id ?? null,
        is_autopick: event.event_type === "draft.autopicked",
        target_role:
          data.target_role ?? board.picks.find((pick) => pick.id === data.pick_id)?.target_role ?? null,
        target_rank_value:
          data.target_rank_value !== undefined
            ? data.target_rank_value
            : board.picks.find((pick) => pick.id === data.pick_id)?.target_rank_value ?? null,
        version:
          data.pick_version ?? board.picks.find((pick) => pick.id === data.pick_id)?.version ?? 0,
      });
      // Mark the picked player as rostered (kept in the list, derived available
      // = status "available"); rosters group by drafted_by_team_id.
      const players = board.players.map((pl) =>
        pl.id === data.picked_player_id
          ? { ...pl, status: "picked" as const, drafted_by_team_id: data.draft_team_id ?? pl.drafted_by_team_id }
          : pl
      );
      return { ...board, picks, players };
    }

    case "draft.pick_started": {
      if (data.pick_id == null) return board;
      const picks = setPick(board, data.pick_id, {
        status: "on_clock",
        clock_expires_at: data.clock_expires_at ?? null,
        // A pick going on the clock starts on its MAIN clock, always: a
        // rollback can put a pick that already ran into overtime back here.
        overtime_started_at: null,
      });
      const current = picks.find((p) => p.id === data.pick_id) ?? null;
      return {
        ...board,
        picks,
        current_pick: current,
        session: { ...board.session, current_pick_id: data.pick_id, status: "live" },
      };
    }

    // The main clock ran out and the grace period began: `clock_expires_at`
    // now carries the OVERTIME deadline, so the ring switches its total too.
    case "draft.overtime_started": {
      if (data.pick_id == null) return board;
      return patchPick(board, data.pick_id, {
        overtime_started_at: data.overtime_started_at ?? null,
        clock_expires_at: data.clock_expires_at ?? null,
        version: data.pick_version ?? board.picks.find((p) => p.id === data.pick_id)?.version ?? 0,
      });
    }

    case "draft.clock_extended": {
      if (data.pick_id == null) return board;
      return patchPick(board, data.pick_id, {
        clock_expires_at: data.clock_expires_at ?? null,
        version: data.pick_version ?? board.picks.find((p) => p.id === data.pick_id)?.version ?? 0,
      });
    }

    case "draft.paused":
      return { ...board, session: { ...board.session, status: "paused" } };

    case "draft.blocked":
      return {
        ...board,
        session: {
          ...board.session,
          status: "paused",
          blocked_reason: data.blocked_reason ?? "role_shortage"
        }
      };

    case "draft.resumed": {
      const picks =
        board.session.current_pick_id != null
          ? setPick(board, board.session.current_pick_id, {
              clock_expires_at: data.clock_expires_at ?? null,
            })
          : board.picks;
      const current = picks.find((p) => p.id === board.session.current_pick_id) ?? board.current_pick;
      return {
        ...board,
        picks,
        current_pick: current,
        session: { ...board.session, status: "live", blocked_reason: null }
      };
    }

    case "draft.completed":
      return {
        ...board,
        current_pick: null,
        session: { ...board.session, status: "completed", current_pick_id: null, blocked_reason: null },
      };

    case "draft.cancelled":
      return { ...board, session: { ...board.session, status: "cancelled" } };

    default:
      return board;
  }
}

export function presenceFromEvent(
  data: DraftEventData,
  occurredAt: string
): DraftPresenceState {
  return {
    users: Object.fromEntries(
      [...new Set(data.user_ids ?? [])].map((userId) => [userId, { last_active_at: occurredAt }])
    ),
    anonymous_viewer_count: Math.max(0, data.anonymous_viewer_count ?? 0)
  };
}

export function canConfirmPick(
  connectionState: RealtimeConnectionState,
  currentPickVersion: number,
  options: DraftPickOptionsResponse | null,
  selection: { playerId: number; role: DraftRole } | null
): boolean {
  if (connectionState !== "connected" || !options || !selection) return false;
  if (options.pick_version !== currentPickVersion) return false;
  return options.options.some(
    (option) =>
      option.player_id === selection.playerId && option.role === selection.role && option.is_safe
  );
}

export interface DraftGating {
  myTeamId: number | null;
  isCaptain: boolean;
  isAdmin: boolean;
  isMyPick: boolean;
  isSpectator: boolean;
}

export function computeGating(
  board: DraftBoard,
  myPlayerIds: readonly number[],
  myAuthUserId: number | null,
  isAdmin: boolean
): DraftGating {
  const ids = new Set(myPlayerIds);
  // Match captaincy by the auth account that registered (reliable) OR by a
  // linked public-player id (fallback).
  const myTeam = board.teams.find(
    (t) =>
      (myAuthUserId != null && t.captain_auth_user_id === myAuthUserId) ||
      (t.captain_user_id != null && ids.has(t.captain_user_id))
  );
  const isCaptain = myTeam != null;
  const onClockTeamId = board.current_pick?.draft_team_id ?? null;
  const isMyPick =
    isCaptain && myTeam!.id === onClockTeamId && board.session.status === "live";
  return {
    myTeamId: myTeam?.id ?? null,
    isCaptain,
    isAdmin,
    isMyPick,
    isSpectator: !isCaptain && !isAdmin,
  };
}
