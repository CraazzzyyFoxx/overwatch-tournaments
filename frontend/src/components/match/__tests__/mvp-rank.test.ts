import { describe, expect, it } from "bun:test";
import { resolveMvpPlacement, mvpRank } from "@/components/match/cells";

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
