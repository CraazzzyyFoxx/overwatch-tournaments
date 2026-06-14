import { describe, expect, it } from "bun:test";

import { getPlayerRowDivisionGrid } from "@/app/admin/players/playerRowDivisionGrid";
import type { DivisionGridVersion } from "@/types/workspace.types";

function createDivisionGridVersion(id: number): DivisionGridVersion {
  return {
    id,
    grid_id: 7,
    version: 1,
    label: `Grid ${id}`,
    status: "published",
    created_from_version_id: null,
    published_at: "2026-04-20T00:00:00Z",
    tiers: [
      {
        number: 1,
        name: "Division 1",
        rank_min: 2000,
        rank_max: null,
        icon_url: "https://example.com/division-1.png",
      },
    ],
  };
}

describe("getPlayerRowDivisionGrid", () => {
  it("returns the tournament division grid when present on the team", () => {
    const grid = createDivisionGridVersion(64);

    expect(
      getPlayerRowDivisionGrid({
        tournament: {
          division_grid_version: grid,
        },
      })
    ).toEqual(grid);
  });

  it("returns null when the team has no tournament division grid", () => {
    expect(getPlayerRowDivisionGrid({ tournament: null })).toBeNull();
    expect(getPlayerRowDivisionGrid({ tournament: { division_grid_version: null } })).toBeNull();
    expect(getPlayerRowDivisionGrid(null)).toBeNull();
  });
});
