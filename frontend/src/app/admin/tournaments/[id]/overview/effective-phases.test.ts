import { describe, expect, it } from "vitest";

import { effectivePhases } from "./effective-phases";

describe("effectivePhases", () => {
  it("is the derived statuses in order, without archived", () => {
    expect(effectivePhases().map((p) => p.key)).toEqual(["announcement", "live", "completed"]);
  });

  it("marks phases up to currentStatus as reached", () => {
    expect(effectivePhases("live").map((p) => [p.key, p.reached])).toEqual([
      ["announcement", true],
      ["live", true],
      ["completed", false]
    ]);
  });

  it("marks nothing reached without currentStatus", () => {
    expect(effectivePhases().every((p) => !p.reached)).toBe(true);
  });

  it("an archived tournament reads as completed", () => {
    const phases = effectivePhases("archived");

    expect(phases.some((p) => p.key === "archived")).toBe(false);
    expect(phases.every((p) => p.reached)).toBe(true);
  });
});
