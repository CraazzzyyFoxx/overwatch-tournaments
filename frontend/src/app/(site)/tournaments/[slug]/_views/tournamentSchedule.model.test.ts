import { describe, expect, it } from "vitest";

import type { Tournament, TournamentStatus } from "@/types/tournament.types";

import { buildTournamentSchedule, nextPhaseBoundary } from "./tournamentSchedule.model";

type Row = Tournament["phase_schedule"][number];

const T = (hour: number, minute = 0) =>
  `2026-08-10T${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}:00Z`;

const at = (hour: number, minute = 0) => Date.parse(T(hour, minute));

function row(status: TournamentStatus, startsAt: string, endsAt: string | null = null): Row {
  return { status, starts_at: startsAt, ends_at: endsAt };
}

function tournament(overrides: Partial<Tournament> = {}) {
  return {
    status: "registration" as TournamentStatus,
    team_formation: "balancer",
    auto_transitions_enabled: true,
    phase_schedule: [
      row("registration", T(10), T(18)),
      row("check_in", T(19), T(19, 45)),
      row("live", T(20))
    ],
    ...overrides
  } as Pick<
    Tournament,
    "status" | "team_formation" | "phase_schedule" | "auto_transitions_enabled"
  >;
}

describe("buildTournamentSchedule", () => {
  it("keeps scheduled phases in lifecycle order and drops unscheduled ones", () => {
    const { segments } = buildTournamentSchedule({
      tournament: tournament({ phase_schedule: [row("live", T(20)), row("registration", T(10))] }),
      now: at(9)
    });

    expect(segments.map((segment) => segment.status)).toEqual(["registration", "live"]);
  });

  it("puts the phase the tournament is in on the timeline even when nobody scheduled it", () => {
    // A balancer tournament forming its teams: registration and check-in are
    // behind it, the start ahead, and `draft` has no row of its own.
    const { segments } = buildTournamentSchedule({
      tournament: tournament({ status: "draft" }),
      now: at(19, 50)
    });

    expect(segments.map((segment) => [segment.status, segment.state])).toEqual([
      ["registration", "done"],
      ["check_in", "done"],
      ["draft", "current"],
      ["live", "upcoming"]
    ]);
    // No time of its own to print or count down from: the countdown belongs to
    // the start, which is the next thing that happens.
    const current = segments[2];
    expect(current.startsAt).toBeNull();
    expect(current.countdownMs).toBeNull();
    expect(segments[3].countdownTo).toBe("start");

    // A lone "now" is not a timeline: with nothing scheduled there is none.
    expect(
      buildTournamentSchedule({
        tournament: tournament({ status: "draft", phase_schedule: [] }),
        now: at(19, 50)
      }).segments
    ).toEqual([]);
  });

  it("shows a scheduled team-formation window whatever the formation", () => {
    const phase_schedule = [row("registration", T(10)), row("draft", T(19)), row("live", T(20))];

    expect(
      buildTournamentSchedule({
        tournament: tournament({ phase_schedule, team_formation: "balancer" }),
        now: at(9)
      }).segments.map((segment) => segment.status)
    ).toEqual(["registration", "draft", "live"]);
  });

  it("flags a current phase whose window has closed, and hands the countdown to the next", () => {
    // Registration ran 10:00–18:00; at 18:30 the status is still registration.
    const { segments } = buildTournamentSchedule({ tournament: tournament(), now: at(18, 30) });
    const [registration, checkIn] = segments;

    expect(registration.state).toBe("current");
    expect(registration.windowClosed).toBe(true);
    expect(registration.countdownMs).toBeNull();
    expect(checkIn.countdownTo).toBe("start");

    const open = buildTournamentSchedule({ tournament: tournament(), now: at(12) }).segments[0];
    expect(open.windowClosed).toBe(false);
    expect(open.countdownTo).toBe("close");
  });

  it("derives segment state from the tournament status, not from the clock", () => {
    // The clock says check-in should have started two hours ago; the status says
    // the tournament never left registration. The status wins.
    const { segments } = buildTournamentSchedule({
      tournament: tournament({ status: "registration" }),
      now: at(21)
    });

    expect(segments.map((segment) => [segment.status, segment.state])).toEqual([
      ["registration", "current"],
      ["check_in", "upcoming"],
      ["live", "upcoming"]
    ]);
  });

  it("marks every segment done once the tournament is past the schedulable phases", () => {
    for (const status of ["playoffs", "completed", "archived"] as TournamentStatus[]) {
      const { segments } = buildTournamentSchedule({
        tournament: tournament({ status }),
        now: at(9)
      });
      expect(segments.every((segment) => segment.state === "done")).toBe(true);
    }
  });

  it("counts the current phase down to its own closing time", () => {
    const { segments } = buildTournamentSchedule({
      tournament: tournament({ status: "check_in" }),
      now: at(19, 30)
    });
    const [registration, checkIn, live] = segments;

    expect(registration.state).toBe("done");
    expect(checkIn.state).toBe("current");
    expect(checkIn.countdownMs).toBe(15 * 60_000);
    // Exactly one boundary is counted down, so two competing timers can never
    // disagree about what happens next.
    expect(live.countdownMs).toBeNull();
  });

  it("counts a current phase down to its own start when the plan has not landed yet", () => {
    // Status moved to live before the planned kickoff — a manual advance. The
    // phase's own start is the nearest boundary, so it wins over both the
    // closing time and any later phase.
    const { segments } = buildTournamentSchedule({
      tournament: tournament({
        status: "check_in",
        phase_schedule: [row("check_in", T(19), T(19, 45)), row("live", T(20))]
      }),
      now: at(18, 40)
    });

    expect(segments[0]).toMatchObject({ countdownMs: 20 * 60_000, countdownTo: "start" });
    expect(segments[1].countdownMs).toBeNull();
  });

  it("counts down to the next phase when the current one has no closing time", () => {
    const { segments } = buildTournamentSchedule({
      tournament: tournament({
        status: "registration",
        phase_schedule: [row("registration", T(10)), row("check_in", T(19), T(19, 45))]
      }),
      now: at(18)
    });

    expect(segments[0]).toMatchObject({ state: "current", countdownMs: null });
    expect(segments[1].countdownMs).toBe(60 * 60_000);
  });

  it("never reports a negative countdown for a plan automation has not executed", () => {
    const { segments } = buildTournamentSchedule({
      tournament: tournament({ status: "registration", auto_transitions_enabled: false }),
      now: at(19, 30)
    });

    expect(segments[0].countdownMs).toBeNull();
    expect(segments[1]).toMatchObject({ state: "upcoming", countdownMs: null });
  });

  it("reports automation being off so the view can label the times as a plan", () => {
    expect(buildTournamentSchedule({ tournament: tournament(), now: at(9) }).automationOff).toBe(
      false
    );
    expect(
      buildTournamentSchedule({
        tournament: tournament({ auto_transitions_enabled: false }),
        now: at(9)
      }).automationOff
    ).toBe(true);
  });

  it("returns no segments when the organizer published no schedule", () => {
    expect(
      buildTournamentSchedule({ tournament: tournament({ phase_schedule: [] }), now: at(9) })
        .segments
    ).toEqual([]);
  });

  it("ignores an unparsable timestamp instead of emitting NaN timings", () => {
    const { segments } = buildTournamentSchedule({
      tournament: tournament({
        status: "check_in",
        phase_schedule: [row("check_in", "not-a-date", T(19, 45))]
      }),
      now: at(19, 30)
    });

    expect(segments[0]).toMatchObject({ state: "current", countdownMs: null });
  });
});

describe("nextPhaseBoundary", () => {
  it("names the current phase's close while its window is open", () => {
    expect(nextPhaseBoundary({ tournament: tournament(), now: at(12) })).toEqual({
      status: "registration",
      at: T(18),
      kind: "close",
      msLeft: at(18) - at(12)
    });
  });

  it("falls through to the next phase's start once the window has closed", () => {
    expect(nextPhaseBoundary({ tournament: tournament(), now: at(18, 30) })).toEqual({
      status: "check_in",
      at: T(19),
      kind: "start",
      msLeft: at(19) - at(18, 30)
    });
  });

  it("is null when nothing lies ahead — a finished tournament or an empty schedule", () => {
    expect(
      nextPhaseBoundary({ tournament: tournament({ status: "completed" }), now: at(23) })
    ).toBeNull();
    expect(
      nextPhaseBoundary({ tournament: tournament({ phase_schedule: [] }), now: at(9) })
    ).toBeNull();
  });
});
