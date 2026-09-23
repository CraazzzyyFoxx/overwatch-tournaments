import {
  SCHEDULABLE_PHASES,
  phaseRank,
  type SchedulablePhase
} from "@/lib/tournament/lifecycle";
import type { Tournament } from "@/types/tournament.types";

/**
 * PLAYOFFS and everything after it depend on the actual course of play and are
 * never scheduled, so they can never appear on this timeline: the hero's status
 * pill carries them instead.
 */

type PhaseSegmentState = "done" | "current" | "upcoming";

export type PhaseSegment = {
  status: SchedulablePhase;
  /**
   * Derived from `tournament.status`, NEVER from `now` vs `startsAt`. A
   * `starts_at` is a plan the worker tick executes, and with automation off it
   * may never be executed at all — comparing clocks would report a phase as
   * running while the tournament sits in the previous one.
   */
  state: PhaseSegmentState;
  /** Planned phase start, ISO-8601. */
  startsAt: string;
  /**
   * When the phase's action window closes, ISO-8601, or null when it stays open
   * for the whole phase. This never advances the status (see
   * `TournamentPhaseSchedule` in `shared/models/tournament/tournament.py`).
   */
  endsAt: string | null;
  /**
   * ms left until this segment's next boundary. Set on at most one segment, so
   * two timers can never disagree about what happens next. Null once that
   * boundary is in the past, so a plan automation did not execute never renders
   * as a negative countdown.
   */
  countdownMs: number | null;
  /**
   * Which boundary `countdownMs` targets. The label follows this rather than the
   * segment's state: a phase can be marked current before its planned start —
   * the organizer advanced the status by hand, or automation is off — and then
   * the phase's own start is the boundary worth counting.
   */
  countdownTo: "start" | "close" | null;
  /** Elapsed fraction (0..1) of a current segment with a closed window. */
  progress: number | null;
  /**
   * The phase is current but its action window has already closed — the
   * tournament waits for the next phase. Registration is the usual case: the
   * status stays `registration` until check-in starts, but nobody can register.
   * The view must not paint such a phase as "now".
   */
  windowClosed: boolean;
};

export type TournamentScheduleModel = {
  segments: PhaseSegment[];
  /**
   * With auto-transitions off the organizer advances phases by hand, so the
   * times are the intended plan rather than a commitment.
   */
  automationOff: boolean;
};

type ScheduleInput = {
  tournament: Pick<
    Tournament,
    "status" | "team_formation" | "phase_schedule" | "auto_transitions_enabled"
  >;
  /**
   * The viewer's clock. Non-nullable on purpose: the page renders its skeleton
   * until hydration supplies one, rather than dressing the pre-hydration render
   * in a zone the viewer does not live in.
   */
  now: number;
};


function epoch(iso: string | null): number | null {
  if (iso === null) return null;
  const value = Date.parse(iso);
  return Number.isFinite(value) ? value : null;
}

export function buildTournamentSchedule({
  tournament,
  now
}: ScheduleInput): TournamentScheduleModel {
  const schedule = tournament.phase_schedule ?? [];

  const currentRank = phaseRank(tournament.status);
  const segments: PhaseSegment[] = [];

  for (const phase of SCHEDULABLE_PHASES) {
    // A balancer tournament has no draft phase at all, even if a stale row says
    // otherwise (the settings form offers all four regardless of formation).
    if (phase === "draft" && tournament.team_formation !== "draft") continue;

    const row = schedule.find((entry) => entry.status === phase);
    // An unscheduled phase has no place on a timeline: it carries no time, and
    // for check-in its absence is exactly what "this tournament has no
    // check-in" means. A row of em-dashes would be noise, not information.
    if (!row) continue;

    const rank = phaseRank(phase);
    segments.push({
      status: phase,
      state: rank < currentRank ? "done" : rank === currentRank ? "current" : "upcoming",
      startsAt: row.starts_at,
      endsAt: row.ends_at,
      countdownMs: null,
      countdownTo: null,
      progress: null,
      windowClosed: false
    });
  }

  const current = segments.find((segment) => segment.state === "current");
  if (current) {
    const startsAt = epoch(current.startsAt);
    const endsAt = epoch(current.endsAt);
    // The phase is marked current but its planned start has not arrived: the
    // status moved ahead of the plan, which is exactly what a manual advance
    // looks like. Its own start is then the nearest boundary, and the only
    // answer to "when does this actually begin".
    if (startsAt !== null && startsAt > now) {
      current.countdownMs = startsAt - now;
      current.countdownTo = "start";
    }
    if (startsAt !== null && endsAt !== null && endsAt > startsAt) {
      current.progress = Math.min(1, Math.max(0, (now - startsAt) / (endsAt - startsAt)));
      if (current.countdownMs === null && endsAt > now) {
        current.countdownMs = endsAt - now;
        current.countdownTo = "close";
      }
    }
    current.windowClosed = endsAt !== null && endsAt <= now;
  }

  if (current?.countdownMs == null) {
    const next = segments.find((segment) => segment.state === "upcoming");
    const startsAt = next ? epoch(next.startsAt) : null;
    if (next && startsAt !== null && startsAt > now) {
      next.countdownMs = startsAt - now;
      next.countdownTo = "start";
    }
  }

  return { segments, automationOff: !tournament.auto_transitions_enabled };
}

export type NextPhaseBoundary = {
  status: SchedulablePhase;
  /** ISO-8601 instant of the boundary. */
  at: string;
  /** Whether the boundary opens the phase or closes its action window. */
  kind: "start" | "close";
  msLeft: number;
};

/**
 * The one upcoming boundary the header chip announces: the current phase's
 * close, else the next phase's start. `null` once the schedule holds nothing
 * ahead of `now` — a finished tournament, or one whose organizer published no
 * times — so the chip renders nothing instead of a stale promise.
 */
export function nextPhaseBoundary(input: ScheduleInput): NextPhaseBoundary | null {
  const { segments } = buildTournamentSchedule(input);
  const carrier = segments.find((segment) => segment.countdownMs !== null);
  if (!carrier || carrier.countdownMs === null || carrier.countdownTo === null) return null;
  const at = carrier.countdownTo === "close" ? carrier.endsAt : carrier.startsAt;
  if (at === null) return null;
  return { status: carrier.status, at, kind: carrier.countdownTo, msLeft: carrier.countdownMs };
}
