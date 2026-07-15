import { describe, expect, it } from "vitest";

import {
  buildDraftSchedule,
  derivePoolReadiness,
  moveCaptain,
  orderCaptainIds,
  roundsForTeamSize,
  SETUP_STEPS,
  validateSetupStep
} from "./setup-model";

describe("draft setup model", () => {
  it("defines the six-step flow and links rounds to roster size", () => {
    expect(SETUP_STEPS).toEqual([
      "config",
      "pool",
      "captains",
      "order",
      "review",
      "ready"
    ]);
    expect(roundsForTeamSize(5)).toBe(4);
    expect(roundsForTeamSize(3)).toBe(2);
  });

  it("reports pool blockers without hiding missing ranks or accounts", () => {
    const readiness = derivePoolReadiness(
      [
        { id: 1, roles: ["tank"], rank: 3000, hasAccount: true, excluded: false },
        { id: 2, roles: ["dps"], rank: null, hasAccount: true, excluded: false },
        { id: 3, roles: ["support"], rank: 2800, hasAccount: false, excluded: false },
        { id: 4, roles: ["support"], rank: 2700, hasAccount: true, excluded: true }
      ],
      2,
      3
    );

    expect(readiness.requiredPlayers).toBe(6);
    expect(readiness.actualPlayers).toBe(3);
    expect(readiness.missingRanks).toBe(1);
    expect(readiness.missingAccounts).toBe(1);
    expect(readiness.excludedPlayers).toBe(1);
    expect(readiness.blockers).toContain("not_enough_players");
  });

  it("reorders captains deterministically for manual order", () => {
    expect(moveCaptain([10, 20, 30], 30, 10)).toEqual([30, 10, 20]);
    expect(moveCaptain([10, 20, 30], 99, 10)).toEqual([10, 20, 30]);
  });

  it("keeps calculated captain order reproducible", () => {
    const ranks = new Map([
      [10, 3100],
      [20, 2500],
      [30, 2800]
    ]);
    expect(orderCaptainIds([10, 20, 30], "weakest_first", ranks, 42)).toEqual([20, 30, 10]);
    expect(orderCaptainIds([10, 20, 30], "strongest_first", ranks, 42)).toEqual([10, 30, 20]);
    expect(orderCaptainIds([10, 20, 30], "random", ranks, 42)).toEqual([30, 10, 20]);
  });

  it("previews snake order for every round", () => {
    expect(buildDraftSchedule([10, 20, 30], 3, "snake", [])).toEqual([
      { round: 1, teamIds: [10, 20, 30], rule: "linear" },
      { round: 2, teamIds: [30, 20, 10], rule: "reverse" },
      { round: 3, teamIds: [10, 20, 30], rule: "linear" }
    ]);
  });

  it("blocks advancing until each step has its required data", () => {
    expect(
      validateSetupStep("config", {
        teamSize: 5,
        pickTimeSeconds: 5,
        captainIds: [],
        poolReady: false,
        previewFeasible: false
      })
    ).toContain("pick_time_out_of_range");
    expect(
      validateSetupStep("captains", {
        teamSize: 5,
        pickTimeSeconds: 45,
        captainIds: [],
        poolReady: true,
        previewFeasible: false
      })
    ).toEqual(["captains_required"]);
    expect(
      validateSetupStep("review", {
        teamSize: 5,
        pickTimeSeconds: 45,
        captainIds: [1, 2],
        poolReady: true,
        previewFeasible: true
      })
    ).toEqual([]);
  });
});
