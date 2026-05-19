import { describe, expect, it } from "bun:test";

import {
  canShowAnalyticsAdminToolbar,
  getAnalyticsRefreshKeys,
  getPreferredAnalyticsAlgorithmId,
} from "@/app/(site)/tournaments/analytics/analytics.helpers";

describe("analytics helpers", () => {
  it("shows the admin toolbar only for users with analytics.update access", () => {
    expect(canShowAnalyticsAdminToolbar(true)).toBe(true);
    expect(canShowAnalyticsAdminToolbar(false)).toBe(false);
  });

  it("prefers Linear as the default analytics algorithm", () => {
    expect(
      getPreferredAnalyticsAlgorithmId([
        { id: 1, name: "Points" },
        { id: 2, name: "OpenSkill + ML" },
        { id: 3, name: "Linear" },
      ]),
    ).toBe(3);
  });

  it("returns the analytics queries that must be invalidated after recalculate", () => {
    expect(getAnalyticsRefreshKeys(11, 42, 7)).toEqual([
      ["analytics", 11, 42],
      ["analytics", 11, 42, 7],
    ]);

    expect(getAnalyticsRefreshKeys(null, 42, null)).toEqual([["analytics", "global", 42]]);
  });
});
