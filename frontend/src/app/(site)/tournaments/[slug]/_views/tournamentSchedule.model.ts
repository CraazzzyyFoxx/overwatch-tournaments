import { nodesOfKind } from "@/lib/tournament/flow-nodes";
import type { FlowNodeScheduleEntry, TournamentFlowNode } from "@/types/flow.types";
import type { Tournament } from "@/types/tournament.types";

/**
 * One window of the timeline is one `flow_node_schedule` row of a registration, formation or stage node: the node's
 * `open` / `check_in` / `start` phase. The leaderboard nodes carry none.
 */

type PhaseSegmentState = "done" | "current" | "upcoming";

type ScheduledKind = "registration" | "formation" | "stage";

/** A node's statuses in the order it passes them, and the status each schedulable phase moves it to (`SCHEDULE_TRANSITIONS`). */
const PHASE_TARGET: Record<ScheduledKind, { order: readonly string[]; target: Record<string, string> }> = {
  registration: {
    order: ["draft", "open", "check_in", "closed"],
    target: { open: "open", check_in: "check_in" }
  },
  formation: { order: ["draft", "forming", "completed"], target: { start: "forming" } },
  stage: { order: ["draft", "ready", "live", "completed"], target: { start: "live" } }
};

export type PhaseSegment = {
  /** Unique per node and phase. */
  key: string;
  kind: ScheduledKind;
  phase: FlowNodeScheduleEntry["phase"];
  nodeName: string;
  /** The tournament has several nodes of this kind, so the phase must name its node. */
  nodeNamed: boolean;
  /**
   * Derived from the node's status, NEVER from `now` vs `startsAt`. A
   * `starts_at` is a plan the scheduler executes, and with automation off it
   * may never be executed at all — comparing clocks would report a phase as
   * running while the node sits in the previous one.
   */
  state: PhaseSegmentState;
  /** Planned phase start, ISO-8601. */
  startsAt: string;
  /**
   * When the phase's action window closes, ISO-8601, or null when it stays open
   * for the whole phase. This never advances the status.
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
   * the organizer advanced the node by hand, or automation is off — and then
   * the phase's own start is the boundary worth counting.
   */
  countdownTo: "start" | "close" | null;
  /**
   * The phase is current but its action window has already closed — the
   * node waits for the next phase. Registration is the usual case: the
   * node stays `open` until check-in starts, but nobody can register.
   * The view must not paint such a phase as "now".
   */
  windowClosed: boolean;
};

/**
 * The i18n key a phase is titled by: the status word for a registration phase, the kind label for a formation (a lone
 * default node's name is English data, so it never prints); null where the node's own name titles the phase — a stage,
 * which carries the organizer's stage name, or one of several formations.
 */
export function phaseTitleKey(
  segment: Pick<PhaseSegment, "kind" | "phase" | "nodeNamed">
):
  | "common.statusBadge.registration"
  | "common.statusBadge.check_in"
  | "tournamentDetail.publicPages.schedule.formation"
  | null {
  if (segment.kind === "formation") return segment.nodeNamed ? null : "tournamentDetail.publicPages.schedule.formation";
  if (segment.kind !== "registration") return null;
  return segment.phase === "open" ? "common.statusBadge.registration" : "common.statusBadge.check_in";
}

export type TournamentScheduleModel = {
  segments: PhaseSegment[];
  /**
   * With auto-transitions off the organizer advances nodes by hand, so the
   * times are the intended plan rather than a commitment.
   */
  automationOff: boolean;
};

type ScheduleInput = {
  tournament: Pick<Tournament, "flow_nodes" | "auto_transitions_enabled">;
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

function segmentsOf(node: TournamentFlowNode, nodeNamed: boolean): PhaseSegment[] {
  const kind = node.kind as ScheduledKind;
  const { order, target } = PHASE_TARGET[kind];
  const rank = order.indexOf(node.status);
  return node.schedule.flatMap((row) => {
    const targetRank = order.indexOf(target[row.phase]);
    // A row of a phase the kind cannot schedule (the server refuses to write one) has no place on a timeline.
    if (targetRank < 0) return [];
    return [
      {
        key: `${node.id}:${row.phase}`,
        kind,
        phase: row.phase,
        nodeName: node.name,
        nodeNamed,
        state: rank < targetRank ? "upcoming" : rank === targetRank ? "current" : "done",
        startsAt: row.starts_at,
        endsAt: row.ends_at ?? null,
        countdownMs: null,
        countdownTo: null,
        windowClosed: false
      } satisfies PhaseSegment
    ];
  });
}

export function buildTournamentSchedule({
  tournament,
  now
}: ScheduleInput): TournamentScheduleModel {
  const segments = (["registration", "formation", "stage"] as const)
    .flatMap((kind) => {
      const nodes = nodesOfKind(tournament, kind);
      return nodes.flatMap((node) => segmentsOf(node, nodes.length > 1));
    })
    .sort((left, right) => (epoch(left.startsAt) ?? 0) - (epoch(right.startsAt) ?? 0));

  const current = segments.find((segment) => segment.state === "current");
  if (current) {
    const startsAt = epoch(current.startsAt);
    const endsAt = epoch(current.endsAt);
    // The phase is marked current but its planned start has not arrived: the
    // node moved ahead of the plan, which is exactly what a manual advance
    // looks like. Its own start is then the nearest boundary, and the only
    // answer to "when does this actually begin".
    if (startsAt !== null && startsAt > now) {
      current.countdownMs = startsAt - now;
      current.countdownTo = "start";
    }
    if (startsAt !== null && endsAt !== null && endsAt > startsAt) {
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

export type NextPhaseBoundary = Pick<PhaseSegment, "kind" | "phase" | "nodeName" | "nodeNamed"> & {
  /** ISO-8601 instant of the boundary. */
  at: string;
  /** Whether the boundary opens the phase or closes its action window. */
  boundary: "start" | "close";
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
  return {
    kind: carrier.kind,
    phase: carrier.phase,
    nodeName: carrier.nodeName,
    nodeNamed: carrier.nodeNamed,
    at,
    boundary: carrier.countdownTo,
    msLeft: carrier.countdownMs
  };
}
