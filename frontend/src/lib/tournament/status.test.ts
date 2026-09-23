import { describe, expect, it } from "vitest";

import { areStreamsVisible, isRegistrationOpen } from "./status";
import type { Tournament, TournamentStatus } from "@/types/tournament.types";

/**
 * The stream gate, spelled out over the WHOLE status vocabulary rather than the
 * two statuses that should pass. A status added to `TournamentStatus` without a
 * decision here fails the exhaustiveness case below instead of silently
 * inheriting "hidden" — which is how the pre-gate bug read in reverse: a
 * registration-phase page showed a permanent "channel is offline" dock and an
 * empty Streams tab.
 */
const EXPECTED: Record<TournamentStatus, boolean> = {
  registration: false,
  // The live player draft is broadcast, so it is the one pre-competition phase
  // whose streams belong on screen.
  draft: true,
  check_in: false,
  live: true,
  // Match play under another name — it shares the "live" presentation bucket,
  // which is what the gate actually tests.
  playoffs: true,
  completed: false,
  archived: false
};

describe("areStreamsVisible", () => {
  for (const [status, expected] of Object.entries(EXPECTED) as [TournamentStatus, boolean][]) {
    it(`${expected ? "shows" : "hides"} streams in ${status}`, () => {
      expect(areStreamsVisible(status)).toBe(expected);
    });
  }
});

const NOW = Date.parse("2026-08-20T12:00:00Z");
const HOUR = 60 * 60 * 1000;

function regWindow(
  ends_at: string | null,
  starts_at = "2026-08-01T00:00:00Z"
): Tournament["phase_schedule"] {
  return [{ status: "registration", starts_at, ends_at }] as Tournament["phase_schedule"];
}

function gate(
  overrides: Partial<Pick<Tournament, "status" | "phase_schedule" | "allow_late_registration">>
) {
  return isRegistrationOpen(
    {
      status: "live",
      phase_schedule: regWindow(null),
      allow_late_registration: false,
      ...overrides
    },
    NOW
  );
}

/**
 * The client mirror of `shared.services.registration_window`. It only decides
 * whether the register button renders, which is exactly why it has to agree with
 * the server: a mirror that drifts either hides a working button or offers one
 * that 400s. `allow_late_registration` spent a release ignored by the backend
 * predicate — these cases pin the boundary it was reinstated with.
 */
describe("isRegistrationOpen", () => {
  it("is closed with no registration row, whatever else is scheduled", () => {
    expect(gate({ phase_schedule: [] as Tournament["phase_schedule"] })).toBe(false);
    expect(
      gate({
        phase_schedule: [
          { status: "check_in", starts_at: "2026-08-01T00:00:00Z", ends_at: null }
        ] as Tournament["phase_schedule"]
      })
    ).toBe(false);
  });

  it("is open inside the window in any non-terminal phase", () => {
    expect(gate({ phase_schedule: regWindow(null) })).toBe(true);
    expect(gate({ phase_schedule: regWindow("2026-08-21T00:00:00Z") })).toBe(true);
  });

  it("is closed once the window has ended", () => {
    expect(gate({ phase_schedule: regWindow("2026-08-19T00:00:00Z") })).toBe(false);
  });

  it("is closed before the window starts", () => {
    expect(
      gate({ phase_schedule: regWindow(null, new Date(NOW + HOUR).toISOString()) })
    ).toBe(false);
  });

  describe("allow_late_registration", () => {
    it("reopens a window that has ended", () => {
      expect(
        gate({ phase_schedule: regWindow("2026-08-19T00:00:00Z"), allow_late_registration: true })
      ).toBe(true);
    });

    it("does not open a tournament with no registration row", () => {
      expect(
        gate({ phase_schedule: [] as Tournament["phase_schedule"], allow_late_registration: true })
      ).toBe(false);
    });

    it("does not open a window that has not started", () => {
      expect(
        gate({
          phase_schedule: regWindow(null, new Date(NOW + HOUR).toISOString()),
          allow_late_registration: true
        })
      ).toBe(false);
    });

    it("cannot beat the terminal floor", () => {
      for (const status of ["completed", "archived"] as const) {
        expect(
          gate({
            status,
            phase_schedule: regWindow("2026-08-19T00:00:00Z"),
            allow_late_registration: true
          })
        ).toBe(false);
      }
    });
  });
});
