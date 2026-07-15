import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "bun:test";

function readTournamentPageSource(fileName: string) {
  return readFileSync(join(import.meta.dir, fileName), "utf8");
}

describe("tournament workspace scoped pages", () => {
  it("uses the tournament workspace when loading bracket encounters", () => {
    const source = readFileSync(
      join(import.meta.dir, "..", "bracket", "TournamentBracketPage.tsx"),
      "utf8"
    );

    expect(source).toContain(
      "tournamentQueryKeys.encounters(tournament.id, tournament.workspace_id)"
    );
    expect(source).toContain("tournament.workspace_id");
  });

  it("uses the tournament workspace when loading public encounters", () => {
    const source = readTournamentPageSource("TournamentEncountersPage.tsx");
    const tableSource = readFileSync(
      join(import.meta.dir, "../../../../../components/EncountersTable.tsx"),
      "utf8"
    );

    expect(source).toContain("tournament.workspace_id");
    expect(tableSource).toContain("encounterService.getAll(");
    expect(tableSource).toContain("workspaceId");
  });

  it("uses the tournament workspace when loading public standings", () => {
    const source = readTournamentPageSource("TournamentStandingsPage.tsx");

    expect(source).toContain("tournamentService.getStandings(");
    expect(source).toContain("tournament.workspace_id");
  });

  it("scopes the teams query with the hydrated tournament workspace", () => {
    const source = readFileSync(join(import.meta.dir, "TournamentTeamsPage.tsx"), "utf8");

    expect(source).toContain(
      "tournamentQueryKeys.teams(tournament.id, tournament.workspace_id)"
    );
    expect(source).toContain("teamService.getAll({");
    expect(source).toContain("tournamentId: tournament.id");
    expect(source).toContain("workspaceId: tournament.workspace_id");
    expect(source).not.toContain("useSelectedWorkspace");
  });

  it("keeps the teams grid to one or two columns", () => {
    const source = readFileSync(join(import.meta.dir, "TournamentTeamsPage.tsx"), "utf8");

    expect(source).toContain("md:grid-cols-2");
    expect(source).not.toContain("xl:grid-cols-3");
  });

  it("shows background updates without replacing stale teams", () => {
    const source = readFileSync(join(import.meta.dir, "TournamentTeamsPage.tsx"), "utf8");

    expect(source).toContain("teamsQuery.isFetching && !teamsQuery.isError ?");
    expect(source).toContain('t("tournamentDetail.pageState.updating")');
  });
});
