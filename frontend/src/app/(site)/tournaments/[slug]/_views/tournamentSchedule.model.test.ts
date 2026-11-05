import { describe, expect, it } from "vitest";

import type { TournamentFlowNode } from "@/types/flow.types";
import type { Tournament } from "@/types/tournament.types";

import {
  buildTournamentSchedule,
  nextPhaseBoundary,
  phaseStatusWord
} from "./tournamentSchedule.model";

const T = (hour: number, minute = 0) =>
  `2026-08-10T${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}:00Z`;

const at = (hour: number, minute = 0) => Date.parse(T(hour, minute));

type Row = TournamentFlowNode["schedule"][number];

function row(phase: string, startsAt: string, endsAt: string | null = null): Row {
  return { phase, starts_at: startsAt, ends_at: endsAt } as Row;
}

function node(
  id: number,
  kind: string,
  status: string,
  schedule: Row[],
  name = `Node ${id}`
): TournamentFlowNode {
  return { id, kind, name, status, config: {}, schedule, stage_id: null } as unknown as TournamentFlowNode;
}

const registrationRows = [row("open", T(10), T(18)), row("check_in", T(19), T(19, 45))];

/** Registration (10:00–18:00, check-in 19:00–19:45) and a stage that starts at 20:00. */
function tournament(
  statuses: { registration?: string; stage?: string } = {},
  overrides: Partial<Pick<Tournament, "flow_nodes" | "auto_transitions_enabled">> = {}
) {
  return {
    auto_transitions_enabled: true,
    flow_nodes: [
      node(1, "registration", statuses.registration ?? "open", registrationRows, "Registration"),
      node(3, "stage", statuses.stage ?? "draft", [row("start", T(20))], "Main stage")
    ],
    ...overrides
  } as Pick<Tournament, "flow_nodes" | "auto_transitions_enabled">;
}

describe("buildTournamentSchedule", () => {
  it("lists every scheduled phase of the nodes by planned start, and drops the unscheduled", () => {
    const { segments } = buildTournamentSchedule({
      tournament: tournament(
        {},
        {
          flow_nodes: [
            node(3, "stage", "draft", [row("start", T(20))]),
            node(2, "formation", "draft", [row("start", T(19, 30))]),
            node(1, "registration", "draft", [row("open", T(10))]),
            node(4, "stage", "draft", [])
          ] as Tournament["flow_nodes"]
        }
      ),
      now: at(9)
    });

    expect(segments.map((segment) => [segment.kind, segment.phase])).toEqual([
      ["registration", "open"],
      ["formation", "start"],
      ["stage", "start"]
    ]);
  });

  it("derives each phase's state from its node's status, not from the clock", () => {
    // The clock says check-in should have started two hours ago; the node never left `open`. The status wins.
    const { segments } = buildTournamentSchedule({ tournament: tournament(), now: at(21) });

    expect(segments.map((segment) => [segment.phase, segment.state])).toEqual([
      ["open", "current"],
      ["check_in", "upcoming"],
      ["start", "upcoming"]
    ]);
  });

  it("marks a phase done once its node is past it", () => {
    const { segments } = buildTournamentSchedule({
      tournament: tournament({ registration: "closed", stage: "live" }),
      now: at(9)
    });

    expect(segments.map((segment) => [segment.phase, segment.state])).toEqual([
      ["open", "done"],
      ["check_in", "done"],
      ["start", "current"]
    ]);
  });

  it("names a registration phase by its node only when the tournament has several", () => {
    expect(buildTournamentSchedule({ tournament: tournament(), now: at(9) }).segments[0].nodeNamed).toBe(false);

    const two = tournament(
      {},
      {
        flow_nodes: [
          node(1, "registration", "open", registrationRows, "Day 1"),
          node(2, "registration", "draft", [row("open", T(12))], "Day 3")
        ] as Tournament["flow_nodes"]
      }
    );
    expect(buildTournamentSchedule({ tournament: two, now: at(9) }).segments.every((s) => s.nodeNamed)).toBe(true);
    expect(phaseStatusWord({ kind: "registration", phase: "open" })).toBe("registration");
    expect(phaseStatusWord({ kind: "registration", phase: "check_in" })).toBe("check_in");
    expect(phaseStatusWord({ kind: "stage", phase: "start" })).toBeNull();
  });

  it("flags a current phase whose window has closed, and hands the countdown to the next", () => {
    // Registration ran 10:00–18:00; at 18:30 the node is still open.
    const { segments } = buildTournamentSchedule({ tournament: tournament(), now: at(18, 30) });
    const [open, checkIn] = segments;

    expect(open.state).toBe("current");
    expect(open.windowClosed).toBe(true);
    expect(open.countdownMs).toBeNull();
    expect(checkIn.countdownTo).toBe("start");

    const ongoing = buildTournamentSchedule({ tournament: tournament(), now: at(12) }).segments[0];
    expect(ongoing.windowClosed).toBe(false);
    expect(ongoing.countdownTo).toBe("close");
  });

  it("counts the current phase down to its own closing time", () => {
    const { segments } = buildTournamentSchedule({
      tournament: tournament({ registration: "check_in" }),
      now: at(19, 30)
    });
    const [open, checkIn, start] = segments;

    expect(open.state).toBe("done");
    expect(checkIn.state).toBe("current");
    expect(checkIn.countdownMs).toBe(15 * 60_000);
    // Exactly one boundary is counted down, so two competing timers can never disagree about what happens next.
    expect(start.countdownMs).toBeNull();
  });

  it("counts a current phase down to its own start when the plan has not landed yet", () => {
    // The node moved before its planned start — a manual advance. The phase's own start is the nearest boundary.
    const { segments } = buildTournamentSchedule({
      tournament: tournament({ registration: "check_in" }),
      now: at(18, 40)
    });

    expect(segments[1]).toMatchObject({ phase: "check_in", countdownMs: 20 * 60_000, countdownTo: "start" });
    expect(segments[2].countdownMs).toBeNull();
  });

  it("counts down to the next phase when the current one has no closing time", () => {
    const { segments } = buildTournamentSchedule({
      tournament: tournament(
        {},
        {
          flow_nodes: [
            node(1, "registration", "open", [row("open", T(10)), row("check_in", T(19), T(19, 45))])
          ] as Tournament["flow_nodes"]
        }
      ),
      now: at(18)
    });

    expect(segments[0]).toMatchObject({ state: "current", countdownMs: null });
    expect(segments[1].countdownMs).toBe(60 * 60_000);
  });

  it("never reports a negative countdown for a plan automation has not executed", () => {
    const { segments } = buildTournamentSchedule({
      tournament: tournament({}, { auto_transitions_enabled: false }),
      now: at(19, 30)
    });

    expect(segments[0].countdownMs).toBeNull();
    expect(segments[1]).toMatchObject({ state: "upcoming", countdownMs: null });
  });

  it("reports automation being off so the view can label the times as a plan", () => {
    expect(buildTournamentSchedule({ tournament: tournament(), now: at(9) }).automationOff).toBe(false);
    expect(
      buildTournamentSchedule({ tournament: tournament({}, { auto_transitions_enabled: false }), now: at(9) })
        .automationOff
    ).toBe(true);
  });

  it("returns no segments when no node has a schedule", () => {
    expect(
      buildTournamentSchedule({
        tournament: tournament({}, { flow_nodes: [node(1, "registration", "open", [])] as Tournament["flow_nodes"] }),
        now: at(9)
      }).segments
    ).toEqual([]);
  });

  it("ignores an unparsable timestamp instead of emitting NaN timings", () => {
    const { segments } = buildTournamentSchedule({
      tournament: tournament(
        { registration: "check_in" },
        {
          flow_nodes: [
            node(1, "registration", "check_in", [row("check_in", "not-a-date", T(19, 45))])
          ] as Tournament["flow_nodes"]
        }
      ),
      now: at(19, 30)
    });

    expect(segments[0]).toMatchObject({ state: "current", countdownMs: null });
  });
});

describe("nextPhaseBoundary", () => {
  it("names the current phase's close while its window is open", () => {
    expect(nextPhaseBoundary({ tournament: tournament(), now: at(12) })).toEqual({
      kind: "registration",
      phase: "open",
      nodeName: "Registration",
      at: T(18),
      boundary: "close",
      msLeft: at(18) - at(12)
    });
  });

  it("falls through to the next phase's start once the window has closed", () => {
    expect(nextPhaseBoundary({ tournament: tournament(), now: at(18, 30) })).toEqual({
      kind: "registration",
      phase: "check_in",
      nodeName: "Registration",
      at: T(19),
      boundary: "start",
      msLeft: at(19) - at(18, 30)
    });
  });

  it("is null when nothing lies ahead — every phase done or no schedule", () => {
    expect(
      nextPhaseBoundary({ tournament: tournament({ registration: "closed", stage: "completed" }), now: at(23) })
    ).toBeNull();
    expect(
      nextPhaseBoundary({
        tournament: tournament({}, { flow_nodes: [] as Tournament["flow_nodes"] }),
        now: at(9)
      })
    ).toBeNull();
  });
});
