import { describe, expect, it } from "vitest";

import { DEFAULT_DIVISION_GRID, getDivisionIconSrc } from "@/lib/division-grid";

describe("getDivisionIconSrc", () => {
  it("uses the site-relative OW2 crest for the fallback ladder", () => {
    expect(getDivisionIconSrc(DEFAULT_DIVISION_GRID, 1)).toBe("/divisions/champion-1.png");
    expect(getDivisionIconSrc({ tiers: [] }, 45)).toBe("/divisions/bronze-5.png");
  });

  it("prefers the grid's own icon_url when the division is on it", () => {
    expect(
      getDivisionIconSrc(
        {
          tiers: [
            {
              number: 3,
              name: "Custom",
              slug: "custom",
              sort_order: 2,
              rank_min: 0,
              rank_max: 1,
              icon_url: "https://s3.example/x.png"
            }
          ]
        },
        3
      )
    ).toBe("https://s3.example/x.png");
  });
});
