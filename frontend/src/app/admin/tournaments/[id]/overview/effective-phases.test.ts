import { describe, expect, it } from "vitest";

import { effectivePhases } from "./effective-phases";

describe("effectivePhases", () => {
  it("balancer tournament skips draft phase", () => {
    expect(
      effectivePhases({
        teamFormation: "balancer",
        schedule: ["registration", "check_in", "live"],
      }).map((p) => p.key),
    ).toEqual([
      "announcement",
      "registration",
      "check_in",
      "live",
      "playoffs",
      "completed",
      "archived",
    ]);
  });

  it("draft tournament keeps draft phase in canonical position", () => {
    expect(
      effectivePhases({
        teamFormation: "draft",
        schedule: ["registration", "draft", "live"],
      }).map((p) => p.key),
    ).toEqual([
      "announcement",
      "registration",
      "check_in",
      "draft",
      "live",
      "playoffs",
      "completed",
      "archived",
    ]);
  });

  it("check_in optional flag set when absent from schedule", () => {
    const withCheckIn = effectivePhases({
      teamFormation: "balancer",
      schedule: ["registration", "check_in", "live"],
    });
    const withoutCheckIn = effectivePhases({
      teamFormation: "balancer",
      schedule: ["registration", "live"],
    });

    expect(withCheckIn.find((p) => p.key === "check_in")?.optional).toBe(false);
    expect(withoutCheckIn.find((p) => p.key === "check_in")?.optional).toBe(
      true,
    );
  });

  it("archived is always optional", () => {
    const phases = effectivePhases({
      teamFormation: "balancer",
      schedule: ["registration", "live"],
    });
    expect(phases.find((p) => p.key === "archived")?.optional).toBe(true);
  });

  it("marks phases up to currentStatus as reached", () => {
    const phases = effectivePhases({
      teamFormation: "balancer",
      schedule: ["registration", "check_in", "live"],
      currentStatus: "live",
    });
    expect(phases.map((p) => [p.key, p.reached])).toEqual([
      ["announcement", true],
      ["registration", true],
      ["check_in", true],
      ["live", true],
      ["playoffs", false],
      ["completed", false],
      ["archived", false],
    ]);
  });

  it("marks nothing reached without currentStatus", () => {
    const phases = effectivePhases({
      teamFormation: "balancer",
      schedule: ["registration", "live"],
    });
    expect(phases.every((p) => !p.reached)).toBe(true);
  });

  it("drift status not in chain is appended as current", () => {
    // Force-transition: balancer tournament pushed into draft status.
    const phases = effectivePhases({
      teamFormation: "balancer",
      schedule: ["registration", "live"],
      currentStatus: "draft",
    });

    expect(phases.map((p) => p.key)).toEqual([
      "announcement",
      "registration",
      "check_in",
      "live",
      "playoffs",
      "completed",
      "archived",
      "draft",
    ]);
    const appended = phases[phases.length - 1];
    expect(appended.reached).toBe(true);
    // Canonical order still drives reached for the regular chain.
    expect(phases.find((p) => p.key === "registration")?.reached).toBe(true);
    expect(phases.find((p) => p.key === "check_in")?.reached).toBe(true);
    expect(phases.find((p) => p.key === "live")?.reached).toBe(false);
  });

  it("completed<->archived cycle does not break the chain", () => {
    // ARCHIVED -> COMPLETED is a valid backward transition in the machine.
    const phases = effectivePhases({
      teamFormation: "balancer",
      schedule: ["registration", "live"],
      currentStatus: "completed",
    });

    expect(phases.map((p) => p.key)).toEqual([
      "announcement",
      "registration",
      "check_in",
      "live",
      "playoffs",
      "completed",
      "archived",
    ]);
    expect(phases.find((p) => p.key === "completed")?.reached).toBe(true);
    expect(phases.find((p) => p.key === "archived")?.reached).toBe(false);
  });
});
