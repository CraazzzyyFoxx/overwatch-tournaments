import { describe, expect, it } from "bun:test";

import {
  buildVerdict,
  canShowAnalyticsAdminToolbar,
  confidenceWord,
  getAnalyticsRefreshKeys,
  getPreferredAnalyticsAlgorithmId,
} from "@/app/(site)/tournaments/analytics/analytics.helpers";

const baseSummary = {
  total_teams: 12,
  total_players: 60,
  anomaly_count: 2,
  divergent_team_count: 3,
  newcomer_count: 5,
  avg_placement_delta: 1.34,
};

describe("analytics helpers", () => {
  it("shows the admin toolbar only for users with analytics.update access", () => {
    expect(canShowAnalyticsAdminToolbar(true)).toBe(true);
    expect(canShowAnalyticsAdminToolbar(false)).toBe(false);
  });

  it("prefers Linear as the default analytics algorithm without tournament data", () => {
    expect(
      getPreferredAnalyticsAlgorithmId([
        { id: 1, name: "Points" },
        { id: 2, name: "OpenSkill + ML" },
        { id: 3, name: "Linear" },
      ]),
    ).toBe(3);
  });

  it("prefers OpenSkill + ML when it has computed data for the tournament", () => {
    expect(
      getPreferredAnalyticsAlgorithmId([
        { id: 1, name: "Points", has_data: true },
        { id: 2, name: "OpenSkill + ML", has_data: true },
        { id: 3, name: "Linear", has_data: true },
      ]),
    ).toBe(2);
  });

  it("falls back to Linear when OpenSkill + ML has no data yet", () => {
    expect(
      getPreferredAnalyticsAlgorithmId([
        { id: 1, name: "Points", has_data: true },
        { id: 2, name: "OpenSkill + ML", has_data: false },
        { id: 3, name: "Linear", has_data: true },
      ]),
    ).toBe(3);
  });

  it("maps confidence to a plain word with a tone", () => {
    expect(confidenceWord(0.9)).toEqual({ label: "High", tone: "high" });
    expect(confidenceWord(0.5)).toEqual({ label: "Medium", tone: "medium" });
    expect(confidenceWord(0.2)).toEqual({ label: "Low", tone: "low" });
    // clamps out-of-range input
    expect(confidenceWord(1.4).label).toBe("High");
  });

  it("builds a verdict as i18n keys + params with supporting clauses", () => {
    const verdict = buildVerdict(baseSummary, 7);

    expect(verdict.headlineParams).toEqual({ teams: 12, players: 60 });
    const keys = verdict.clauses.map((clause) => clause.key);
    expect(keys).toContain("analytics.verdict.moves");
    expect(keys).toContain("analytics.verdict.flags");
    expect(keys).toContain("analytics.verdict.misses");
    expect(keys).toContain("analytics.verdict.newcomers");
    // forecast-accuracy clause is always last
    expect(verdict.clauses.at(-1)).toEqual({
      key: "analytics.verdict.forecast",
      params: { delta: "1.3" },
    });
    // the flags clause is toned as a warning
    expect(verdict.clauses.find((c) => c.key === "analytics.verdict.flags")?.tone).toBe("warn");
    expect(verdict.clauses.find((c) => c.key === "analytics.verdict.moves")?.params).toEqual({
      count: 7,
    });
  });

  it("omits optional clauses when everything is calm", () => {
    const calm = {
      total_teams: 8,
      total_players: 40,
      anomaly_count: 0,
      divergent_team_count: 0,
      newcomer_count: 0,
      avg_placement_delta: 0.4,
    };

    const verdict = buildVerdict(calm, 0);

    expect(verdict.clauses).toEqual([
      { key: "analytics.verdict.forecast", params: { delta: "0.4" } },
    ]);
  });

  it("returns the analytics queries that must be invalidated after recalculate", () => {
    expect(getAnalyticsRefreshKeys(11, 42, 7)).toEqual([
      ["analytics", 11, 42],
      ["analytics", 11, 42, 7],
    ]);

    expect(getAnalyticsRefreshKeys(null, 42, null)).toEqual([["analytics", "global", 42]]);
  });
});
