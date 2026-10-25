import type { SortingFn } from "@tanstack/react-table";

import type { Tone } from "@/components/ui/tone";
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
  teams_unknown: "phase.teamsUnknown",
  readiness: "phase.readiness",
  map: "phase.mapVeto",
  hero: "phase.heroBans",
  report: "phase.reporting",
  done: "phase.done",
  idle: "phase.idle"
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
  game_disputed: "attention.mapDisputed",
  result_disputed: "attention.resultDisputed",
  awaiting_choice: "attention.waitingChoice",
  overdue: "attention.turnOverdue",
  late_not_ready: "attention.lateNotReady"
};

export const ATTENTION_TONE: Record<PregameRoomAttention, Tone> = {
  game_disputed: "danger",
  result_disputed: "danger",
  awaiting_choice: "warning",
  overdue: "warning",
  late_not_ready: "warning"
};

/** `ban`/`pick`/`protect` as a column reads it. Unknown actions pass through. */
export function stepActionLabel(action: string): string {
  if (action === "ban") return "action.ban";
  if (action === "pick") return "action.pick";
  if (action === "protect") return "action.protect";
  return action;
}

/**
 * The one step a row's "current step" column should describe.
 *
 * Read off the sessions rather than off `phase`: a map veto that finished
 * leaves an encounter in `hero`, but an encounter can also sit in `report`
 * with a hero session still waiting on a loser's choice, and the column must
 * name that rather than go blank. Map wins a tie because it always runs first.
 *
 * A session an organizer cancelled has no open step at all, yet it is the
 * reason the room looks stalled — so it is named too, after every live one.
 */
export function currentStep(
  room: PregameRoomRow
): { kind: "map" | "hero"; summary: PregameKindSummary } | null {
  for (const kind of ["map", "hero"] as const) {
    const summary = room[kind];
    if (summary?.status !== "active") continue;
    if (summary.step_index != null || summary.awaiting_choice) return { kind, summary };
  }
  for (const kind of ["map", "hero"] as const) {
    const summary = room[kind];
    if (summary?.status === "cancelled") return { kind, summary };
  }
  return null;
}

/** Kick-off as a number to compare; a room with no time yet is later than any time. */
function kickoff(room: PregameRoomRow): number {
  return room.scheduled_at ? Date.parse(room.scheduled_at) : Number.POSITIVE_INFINITY;
}

/**
 * The "Scheduled" column, oldest first; the table flips it for its default,
 * newest first.
 *
 * A room with no time yet counts as the latest — a match nobody has planned
 * yet, not an old one — so it heads the newest-first list (two of them
 * subtract to NaN, which falls through to the tie-break). Equal times fall
 * back to the bracket: the browser hands the rows over in the server's bracket
 * order reversed, so a higher index is an earlier bracket position. The
 * tie-break lives here rather than in TanStack's own index fallback because
 * only the comparator's result is flipped with the direction.
 */
export const sortByKickoff: SortingFn<PregameRoomRow> = (a, b) =>
  kickoff(a.original) - kickoff(b.original) || b.index - a.index;

/** The order a room moves through its phases: the "Phase" column sorts on this, not on the key's spelling. */
const PHASE_RANK: Record<PregameRoomPhase, number> = {
  teams_unknown: 0,
  readiness: 1,
  map: 2,
  hero: 3,
  idle: 4,
  report: 5,
  done: 6
};

export const sortByPhase: SortingFn<PregameRoomRow> = (a, b) =>
  PHASE_RANK[a.original.phase] - PHASE_RANK[b.original.phase];
