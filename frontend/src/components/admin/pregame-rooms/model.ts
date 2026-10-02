import type { Tone } from "@/components/kit/tone";
import type {
  PregameKindSummary,
  PregameRoomAttention,
  PregameRoomPhase,
  PregameRoomRow
} from "@/types/admin.types";

/**
 * How often the overview re-reads the tournament's rooms.
 *
 * The rooms move on things that reach no client: a captain pressing ready, a
 * turn timer running out, a report landing. There is no realtime topic for the
 * *set* of rooms (only per-encounter ones, which would mean subscribing to
 * every encounter of the tournament), so this poll IS the live update. React
 * Query suspends it while the browser tab is hidden, so an organizer who
 * leaves the screen open costs nothing.
 *
 * The page and the sub-tab badge share it along with
 * `adminQueryKeys.pregameRooms`, so mounting both costs one request (TanStack
 * dedupes the observers) and the badge never disagrees with the table.
 */
export const PREGAME_ROOMS_REFETCH_MS = 10_000;

export const PHASE_LABEL: Record<PregameRoomPhase, string> = {
  teams_unknown: "Teams unknown",
  readiness: "Readiness",
  map: "Map veto",
  hero: "Hero bans",
  report: "Reporting",
  done: "Done",
  idle: "Idle"
};

export const PHASE_TONE: Record<PregameRoomPhase, Tone> = {
  teams_unknown: "neutral",
  readiness: "warning",
  map: "accent",
  hero: "accent",
  report: "info",
  done: "success",
  idle: "neutral"
};

export const ATTENTION_LABEL: Record<PregameRoomAttention, string> = {
  game_disputed: "Map disputed",
  result_disputed: "Result disputed",
  awaiting_choice: "Waiting on a choice",
  overdue: "Turn overdue",
  late_not_ready: "Late, not ready"
};

export const ATTENTION_TONE: Record<PregameRoomAttention, Tone> = {
  game_disputed: "danger",
  result_disputed: "danger",
  awaiting_choice: "warning",
  overdue: "warning",
  late_not_ready: "warning"
};

/** `ban`/`pick`/`protect` as a column reads it. Unknown actions pass through. */
export function stepActionLabel(action: string | null): string {
  if (action === "ban") return "Ban";
  if (action === "pick") return "Pick";
  if (action === "protect") return "Protect";
  return action ?? "—";
}

/**
 * The one step a row's "current step" column should describe.
 *
 * Read off the sessions rather than off `phase`: a map veto that finished
 * leaves an encounter in `hero`, but an encounter can also sit in `report`
 * with a hero session still waiting on a loser's choice, and the column must
 * name that rather than go blank. Map wins a tie because it always runs first.
 */
export function currentStep(
  room: PregameRoomRow
): { kind: "map" | "hero"; summary: PregameKindSummary } | null {
  for (const kind of ["map", "hero"] as const) {
    const summary = room[kind];
    if (summary?.status !== "active") continue;
    if (summary.step_index != null || summary.awaiting_choice) return { kind, summary };
  }
  return null;
}

/**
 * Default order: whoever needs a human, then by kick-off, then whatever the
 * server decided (stage order, round, id) — which is already the order an
 * organizer reads a bracket in, so it is the right tie-break.
 *
 * Unscheduled rooms sink below scheduled ones rather than to the top: a row
 * with no time is not urgent, it is unplanned.
 */
export function sortRooms(rooms: readonly PregameRoomRow[]): PregameRoomRow[] {
  return rooms.map((room, index) => ({ room, index })).sort((a, b) => {
    const attention = Number(b.room.attention.length > 0) - Number(a.room.attention.length > 0);
    if (attention !== 0) return attention;
    const aAt = a.room.scheduled_at ? Date.parse(a.room.scheduled_at) : Number.POSITIVE_INFINITY;
    const bAt = b.room.scheduled_at ? Date.parse(b.room.scheduled_at) : Number.POSITIVE_INFINITY;
    if (aAt !== bAt) return aAt - bAt;
    return a.index - b.index;
  }).map((entry) => entry.room);
}
