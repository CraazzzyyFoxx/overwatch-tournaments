import { describe, expect, it } from "bun:test";

import {
  buildCommunityVerdict,
  buildKpiRail,
  buildVerdict,
  canShowAnalyticsAdminToolbar,
  confidenceWord,
  deriveImpact,
  formatAnalyticsNumber,
  getAnalyticsRefreshKeys,
  getPreferredAnalyticsAlgorithmId,
  ordinal,
  resolveImpact,
} from "@/app/(site)/tournaments/analytics/analytics.helpers";

describe("formatAnalyticsNumber", () => {
  it("keeps trailing zeros of whole numbers (impact 100 is not '1')", () => {
    expect(formatAnalyticsNumber(100, 0)).toBe("100");
    expect(formatAnalyticsNumber(90, 0)).toBe("90");
    expect(formatAnalyticsNumber(50, 0)).toBe("50");
    expect(formatAnalyticsNumber(10, 0)).toBe("10");
  });

  it("drops only fractional trailing zeros", () => {
    expect(formatAnalyticsNumber(2.0)).toBe("2");
    expect(formatAnalyticsNumber(1.5, 2)).toBe("1.5");
    expect(formatAnalyticsNumber(1.23, 2)).toBe("1.23");
    expect(formatAnalyticsNumber(2.28, 2)).toBe("2.28");
  });

  it("handles null, NaN and negative zero", () => {
    expect(formatAnalyticsNumber(null)).toBe("0");
    expect(formatAnalyticsNumber(Number.NaN)).toBe("0");
    expect(formatAnalyticsNumber(-0.001, 2)).toBe("0");
  });
});

type TestPlayer = {
  points: number;
  predicted_direction: "promote" | "demote" | "flat";
  anomalies: unknown[];
};

const player = (
  predicted_direction: TestPlayer["predicted_direction"],
  points = 0,
  flagged = false,
): TestPlayer => ({
  points,
  predicted_direction,
  anomalies: flagged ? [{}] : [],
});

const team = (...players: TestPlayer[]) => ({ players });

const verdictTeam = (
  id: number,
  name: string,
  placement: number | null,
  predicted_place: number | null,
  placement_delta: number | null,
) => ({ id, name, placement, predicted_place, placement_delta });

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

  it("derives a clamped 0–100 impact from raw shift points", () => {
    expect(deriveImpact(0)).toBe(40);
    expect(deriveImpact(0.4)).toBe(50);
    // tails clamp so a bar never reads as empty or full
    expect(deriveImpact(-5)).toBe(3);
    expect(deriveImpact(5)).toBe(99);
    expect(deriveImpact(Number.NaN)).toBe(50);
  });

  it("prefers the v2 impact score only when allowed and present", () => {
    expect(resolveImpact({ points: 0 }, { impact_score: 88 }, true)).toBe(88);
    // not allowed → fall back to derived
    expect(resolveImpact({ points: 0 }, { impact_score: 88 }, false)).toBe(40);
    // allowed but no row → derived
    expect(resolveImpact({ points: 0.4 }, undefined, true)).toBe(50);
  });

  it("formats English ordinals", () => {
    expect(ordinal(1)).toBe("1st");
    expect(ordinal(2)).toBe("2nd");
    expect(ordinal(3)).toBe("3rd");
    expect(ordinal(4)).toBe("4th");
    expect(ordinal(11)).toBe("11th");
    expect(ordinal(22)).toBe("22nd");
  });

  it("names the story and the let-down by largest placement delta", () => {
    const verdict = buildCommunityVerdict([
      verdictTeam(1, "Story", 1, 5, 4), // beat forecast hardest
      verdictTeam(2, "Steady", 6, 6, 0),
      verdictTeam(3, "Letdown", 11, 4, -7), // missed forecast hardest
    ]);

    expect(verdict.story?.id).toBe(1);
    expect(verdict.letdown?.id).toBe(3);
  });

  it("omits a verdict side when there is no genuine surprise", () => {
    const verdict = buildCommunityVerdict([
      verdictTeam(1, "A", 2, 2, 0),
      verdictTeam(2, "B", 4, 5, 1), // only an overperformer, no let-down
    ]);

    expect(verdict.story?.id).toBe(2);
    expect(verdict.letdown).toBeUndefined();
  });

  it("ignores teams without a placement delta in the verdict", () => {
    expect(buildCommunityVerdict([verdictTeam(1, "A", null, null, null)])).toEqual({});
  });

  it("builds the six KPIs with climber/dropper counts and tones", () => {
    const kpis = buildKpiRail(
      {
        avg_confidence: 0.78,
        anomaly_count: 4,
        divergent_team_count: 3,
        newcomer_count: 5,
      },
      [
        team(player("promote"), player("promote"), player("flat")),
        team(player("demote"), player("flat")),
      ],
    );

    const byId = Object.fromEntries(kpis.map((kpi) => [kpi.id, kpi]));
    expect(kpis).toHaveLength(6);
    expect(byId.climbing.value).toBe(2);
    expect(byId.dropping.value).toBe(1);
    expect(byId.watch.value).toBe(4);
    expect(byId.avgConfidence.display).toBe("78%");
    expect(byId.upsets.value).toBe(3);
    expect(byId.newFaces.value).toBe(5);
    expect(byId.climbing.tone).toBe("up");
    expect(byId.watch.tone).toBe("warn");
  });
});
