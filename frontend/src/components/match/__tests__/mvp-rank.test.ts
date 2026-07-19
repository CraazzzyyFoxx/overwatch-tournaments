import { describe, expect, it } from "bun:test";
import { formatOverperformance, resolveMvpPlacement, mvpRank } from "@/components/match/cells";

describe("resolveMvpPlacement", () => {
  it("prefers impact_rank over legacy performance", () => {
    expect(resolveMvpPlacement({ impact_rank: 2, performance: 1 })).toBe(2);
  });
  it("falls back to performance for legacy matches", () => {
    expect(resolveMvpPlacement({ impact_rank: null, performance: 3 })).toBe(3);
  });
  it("returns null when neither exists", () => {
    expect(resolveMvpPlacement({})).toBeNull();
  });
});

describe("mvpRank", () => {
  it("maps 1..3 to medals", () => {
    expect(mvpRank(1)).toBe("gold");
    expect(mvpRank(4)).toBe("default");
  });
});

describe("formatOverperformance", () => {
  it("formats a positive score as raised with a plus sign", () => {
    expect(formatOverperformance(2.5)).toEqual({ text: "+2.5", raised: true });
  });
  it("formats a negative score as not raised with a minus sign", () => {
    expect(formatOverperformance(-1)).toEqual({ text: "−1.0", raised: false });
  });
  it("treats exactly zero as raised", () => {
    expect(formatOverperformance(0)).toEqual({ text: "+0.0", raised: true });
  });
  it("returns null for absent or NaN scores", () => {
    expect(formatOverperformance(null)).toBeNull();
    expect(formatOverperformance(undefined)).toBeNull();
    expect(formatOverperformance(Number.NaN)).toBeNull();
  });
});
