import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "bun:test";

import type { Standings } from "@/types/tournament.types";

import { toBracketStandingRows } from "./BracketLeanStandings";

describe("BracketLeanStandings", () => {
  it("presents only placement and team identity when match history is absent", () => {
    const leanStanding = {
      id: 1,
      tournament_id: 72,
      team_id: 8,
      stage_id: 301,
      stage_item_id: null,
      position: 2,
      overall_position: 4,
      team: {
        id: 8,
        name: "Clockwork",
        group: { name: "A" }
      }
    } as unknown as Standings;

    const rows = toBracketStandingRows([leanStanding], false);

    expect(rows).toEqual([
      {
        key: "301-8",
        placement: 4,
        teamLabel: "Clockwork",
        groupLabel: "A"
      }
    ]);
    expect(Object.keys(rows[0])).not.toContain("record");
    expect(Object.keys(rows[0])).not.toContain("mapScore");
    expect(Object.keys(rows[0])).not.toContain("mapDifferential");
    expect(Object.keys(rows[0])).not.toContain("form");
    expect(JSON.stringify(rows)).not.toContain("0-0");
  });

  it("leaves the full rich standings table intact but does not use it in the lean bracket", () => {
    const bracketSource = readFileSync(join(import.meta.dir, "TournamentBracketPage.tsx"), "utf8");
    const richTableSource = readFileSync(
      join(import.meta.dir, "../../../../../components/StandingsTable.tsx"),
      "utf8"
    );

    expect(bracketSource).not.toContain('import StandingsTable from "@/components/StandingsTable"');
    expect(bracketSource).toContain("BracketLeanStandings");
    expect(richTableSource).toContain("standing.matches_history ?? []");
    expect(richTableSource).toContain('t("standings.colForm")');
    expect(richTableSource).toContain('t("standings.colMapDiff")');
  });
});
