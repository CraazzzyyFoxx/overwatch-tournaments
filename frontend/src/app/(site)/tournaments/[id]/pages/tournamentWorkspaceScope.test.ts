import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "bun:test";

function readTournamentPageSource(fileName: string) {
  return readFileSync(join(import.meta.dir, fileName), "utf8");
}

describe("tournament workspace scoped pages", () => {
  it("uses the tournament workspace when loading the bracket page encounters", () => {
    const source = readFileSync(join(import.meta.dir, "..", "bracket", "TournamentBracketPage.tsx"), "utf8");

    expect(source).toContain('queryKey: ["encounters", "tournament", tournament.id, tournament.workspace_id]');
    expect(source).toContain("tournament.workspace_id");
  });

  it("uses the tournament workspace when loading public encounters", () => {
    const source = readTournamentPageSource("TournamentEncountersPage.tsx");
    const tableSource = readFileSync(join(import.meta.dir, "../../../../../components/EncountersTable.tsx"), "utf8");

    expect(source).toContain("tournament.workspace_id");
    expect(tableSource).toContain("encounterService.getAll(");
    expect(tableSource).toContain("workspaceId");
  });

  it("uses the tournament workspace when loading public standings", () => {
    const source = readTournamentPageSource("TournamentStandingsPage.tsx");

    expect(source).toContain("tournamentService.getStandings(");
    expect(source).toContain("tournament.workspace_id");
  });
});
