import type { RealtimeEventEnvelope } from "@/types/realtime.types";
import type {
  DraftBoard,
  DraftEventData,
  DraftPick,
  DraftPickStatus,
} from "@/types/draft.types";

export const URGENT_THRESHOLD_MS = 10_000;

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
      });
      const current = picks.find((p) => p.id === data.pick_id) ?? null;
      return {
        ...board,
        picks,
        current_pick: current,
        session: { ...board.session, current_pick_id: data.pick_id, status: "live" },
      };
    }

    case "draft.paused":
      return { ...board, session: { ...board.session, status: "paused" } };

    case "draft.resumed": {
      const picks =
        board.session.current_pick_id != null
          ? setPick(board, board.session.current_pick_id, {
              clock_expires_at: data.clock_expires_at ?? null,
            })
          : board.picks;
      const current = picks.find((p) => p.id === board.session.current_pick_id) ?? board.current_pick;
      return { ...board, picks, current_pick: current, session: { ...board.session, status: "live" } };
    }

    case "draft.completed":
      return {
        ...board,
        current_pick: null,
        session: { ...board.session, status: "completed", current_pick_id: null },
      };

    case "draft.cancelled":
      return { ...board, session: { ...board.session, status: "cancelled" } };

    default:
      return board;
  }
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
  isAdmin: boolean
): DraftGating {
  const ids = new Set(myPlayerIds);
  const myTeam = board.teams.find(
    (t) => t.captain_user_id != null && ids.has(t.captain_user_id)
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
