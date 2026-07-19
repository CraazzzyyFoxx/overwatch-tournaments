import { describe, expect, it } from "vitest";

import { getComparePageHeroModel } from "./compare-page-hero.model";

describe("compare page hero model", () => {
  it("keeps data-dependent stats empty until a subject is selected", () => {
    expect(
      getComparePageHeroModel({
        hasSubject: false,
        hasData: false,
        isLoading: false,
        scope: "overall",
        baseline: "global",
        sampleSize: 0,
        metricCount: 0
      })
    ).toEqual({
      scope: "overall",
      baseline: "global",
      sampleSize: "—",
      metricCount: "—"
    });
  });

  it("does not flash zeroes during the first load", () => {
    expect(
      getComparePageHeroModel({
        hasSubject: true,
        hasData: false,
        isLoading: true,
        scope: "hero",
        baseline: "target_user",
        sampleSize: 0,
        metricCount: 0
      })
    ).toMatchObject({ sampleSize: "—", metricCount: "—" });
  });

  it.each([
    ["global", "global"],
    ["cohort", "cohort"],
    ["target_user", "target_user"]
  ] as const)("preserves the %s baseline state", (baseline, expected) => {
    expect(
      getComparePageHeroModel({
        hasSubject: true,
        hasData: true,
        isLoading: false,
        scope: "overall",
        baseline,
        sampleSize: 18,
        metricCount: 14
      }).baseline
    ).toBe(expected);
  });

  it("reports Hero / Map scope, sample size, and ready metric count", () => {
    expect(
      getComparePageHeroModel({
        hasSubject: true,
        hasData: true,
        isLoading: false,
        scope: "hero",
        baseline: "cohort",
        sampleSize: 11,
        metricCount: 7
      })
    ).toEqual({
      scope: "hero",
      baseline: "cohort",
      sampleSize: 11,
      metricCount: 7
    });
  });
});
