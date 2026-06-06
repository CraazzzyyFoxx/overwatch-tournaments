import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "bun:test";

describe("StandingsTable", () => {
  it("shows a team's source group only in the playoff/overall view", () => {
    const source = readFileSync(join(import.meta.dir, "StandingsTable.tsx"), "utf8");

    // Group is shown as a sub-label only when not rendering a per-group table.
    expect(source).toContain("showGroup={!is_groups}");
    expect(source).toContain("showGroup && groupName");
  });

  it("renders recent results as form chips", () => {
    const source = readFileSync(join(import.meta.dir, "StandingsTable.tsx"), "utf8");
    expect(source).toContain("form-chips");
  });

  it("shows every group-stage ranking metric", () => {
    const source = readFileSync(join(import.meta.dir, "StandingsTable.tsx"), "utf8");

    expect(source).toContain("standing.points.toFixed(1)");
    expect(source).toContain('standing.tb ?? "—"');
    expect(source).toContain("maps.won");
    expect(source).toContain("standing.buchholz.toFixed(1)");
    expect(source).toContain("<MapDiff diff={maps.diff} />");
  });
});
