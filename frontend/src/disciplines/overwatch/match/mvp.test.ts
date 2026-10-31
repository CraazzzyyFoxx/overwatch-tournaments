import { describe, expect, it } from "vitest";
import type { MatchWithUserStats } from "@/types/user.types";
import { topContributions } from "./MvpOrdinal";
import { formatOverperformance, mvpRank, overperformanceBadge, resolveMvpPlacement } from "./mvp";

describe("resolveMvpPlacement", () => {
  it("reads impact_rank", () => {
    expect(resolveMvpPlacement({ impact_rank: 2 })).toBe(2);
  });
  it("returns null when impact_rank is absent, never 0", () => {
    expect(resolveMvpPlacement({})).toBeNull();
    expect(resolveMvpPlacement(undefined)).toBeNull();
  });
});

describe("overperformanceBadge", () => {
  const match = (facts: Record<string, number> | null) =>
    ({ viewer: facts ? { facts } : null }) as unknown as Pick<MatchWithUserStats, "viewer">;
  it("is the stored overperformance_badge fact", () => {
    expect(overperformanceBadge(match({ overperformance_badge: 1 }))).toBe(true);
    expect(overperformanceBadge(match({ overperformance_badge: 0, overperformance_score: 9 }))).toBe(false);
    expect(overperformanceBadge(match({ overperformance_score: 9 }))).toBe(false);
    expect(overperformanceBadge(match(null))).toBe(false);
  });
});

describe("mvpRank", () => {
  it("maps 1..3 to medals", () => {
    expect(mvpRank(1)).toBe("gold");
    expect(mvpRank(4)).toBe("default");
  });
});

describe("topContributions", () => {
  it("keeps the top 3 positive then the top 2 negative contributions of the map", () => {
    const facts = {
      contrib_eliminations: 0.4,
      contrib_final_blows: 1.2,
      contrib_hero_damage_dealt: 0.9,
      contrib_healing_dealt: 0.1,
      contrib_deaths: -0.5,
      contrib_first_deaths: -1.5,
      contrib_damage_taken: -0.1,
      contrib_unknown_stat: 9,
      impact_rank: 1
    };
    expect(topContributions(facts).map(({ value }) => value)).toEqual([1.2, 0.9, 0.4, -1.5, -0.5]);
    expect(topContributions(undefined)).toEqual([]);
  });
  it("drops contributions that would read 0.00", () => {
    const facts = { contrib_eliminations: 0.004, contrib_deaths: -0.003, contrib_final_blows: 0.02 };
    expect(topContributions(facts).map(({ value }) => value)).toEqual([0.02]);
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
  it("takes a precision for the small contribution values", () => {
    expect(formatOverperformance(-0.034, 2)).toEqual({ text: "−0.03", raised: false });
  });
  it("returns null for absent or NaN scores", () => {
    expect(formatOverperformance(null)).toBeNull();
    expect(formatOverperformance(undefined)).toBeNull();
    expect(formatOverperformance(Number.NaN)).toBeNull();
  });
});
