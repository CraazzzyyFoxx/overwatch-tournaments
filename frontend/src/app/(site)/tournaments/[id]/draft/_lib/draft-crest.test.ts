import { describe, expect, it } from "vitest";
import { teamCrest } from "./draft-crest";

describe("teamCrest", () => {
  it("takes the first letter, uppercased", () => {
    expect(teamCrest({ id: 1, name: "void syndicate" }).initial).toBe("V");
  });
  it("falls back to # for empty/symbol names", () => {
    expect(teamCrest({ id: 2, name: "  " }).initial).toBe("#");
  });
  it("hue is deterministic per id and within 0..359", () => {
    const a = teamCrest({ id: 7, name: "Nova" }).hue;
    expect(a).toBe(teamCrest({ id: 7, name: "Other" }).hue);
    expect(a).toBeGreaterThanOrEqual(0);
    expect(a).toBeLessThan(360);
  });
  it("wraps ids whose unrounded hue would hit exactly 360", () => {
    const hue = teamCrest({ id: 610, name: "Wraparound" }).hue;
    expect(hue).toBeGreaterThanOrEqual(0);
    expect(hue).toBeLessThan(360);
    expect(hue).toBe(0);
  });
});
