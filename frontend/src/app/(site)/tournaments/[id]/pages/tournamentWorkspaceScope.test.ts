import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "bun:test";

type TeamsQueryPresentation = {
  initialState: "skeleton" | "error" | null;
  contentState: "empty" | "teams" | null;
  showUpdating: boolean;
  showRefreshError: boolean;
};

type GetTeamsQueryPresentation = (input: {
  data: unknown;
  teamCount: number;
  isPending: boolean;
  isError: boolean;
  isFetching: boolean;
}) => TeamsQueryPresentation;

const teamsPageModule = (await import("./TournamentTeamsPage")) as typeof import("./TournamentTeamsPage") & {
  getTeamsQueryPresentation?: GetTeamsQueryPresentation;
};

function readTournamentPageSource(fileName: string) {
  return readFileSync(join(import.meta.dir, fileName), "utf8");
}

describe("tournament workspace scoped pages", () => {
  it("keeps cached empty content visible while its refresh is updating", () => {
    expect(
      teamsPageModule.getTeamsQueryPresentation?.({
        data: { results: [], total: 0 },
        teamCount: 0,
        isPending: false,
        isError: false,
        isFetching: true
      })
    ).toEqual({
      initialState: null,
      contentState: "empty",
      showUpdating: true,
      showRefreshError: false
    });
  });

  it("keeps cached empty content visible below a stale refresh error", () => {
    expect(
      teamsPageModule.getTeamsQueryPresentation?.({
        data: { results: [], total: 0 },
        teamCount: 0,
        isPending: false,
        isError: true,
        isFetching: false
      })
    ).toEqual({
      initialState: null,
      contentState: "empty",
      showUpdating: false,
      showRefreshError: true
    });
  });

  it("keeps an initial error without cached data blocking", () => {
    expect(
      teamsPageModule.getTeamsQueryPresentation?.({
        data: undefined,
        teamCount: 0,
        isPending: false,
        isError: true,
        isFetching: false
      })
    ).toEqual({
      initialState: "error",
      contentState: null,
      showUpdating: false,
      showRefreshError: false
    });
  });

  it("keeps an initial pending query without cached data on the skeleton", () => {
    expect(
      teamsPageModule.getTeamsQueryPresentation?.({
        data: undefined,
        teamCount: 0,
        isPending: true,
        isError: false,
        isFetching: true
      })
    ).toEqual({
      initialState: "skeleton",
      contentState: null,
      showUpdating: false,
      showRefreshError: false
    });
  });

  it("renders the blocking initial error before the no-content skeleton fallback", () => {
    const source = readFileSync(join(import.meta.dir, "TournamentTeamsPage.tsx"), "utf8");
    const initialErrorBranch = source.indexOf('presentation.initialState === "error"');
    const skeletonBranch = source.indexOf('presentation.initialState === "skeleton"');

    expect(initialErrorBranch).toBeGreaterThan(-1);
    expect(skeletonBranch).toBeGreaterThan(-1);
    expect(initialErrorBranch).toBeLessThan(skeletonBranch);
  });

  it("uses the tournament workspace when loading bracket encounters", () => {
    const source = readFileSync(
      join(import.meta.dir, "..", "bracket", "bracketData.ts"),
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

  it("scales the teams grid from one column up to three on wide screens", () => {
    const source = readFileSync(join(import.meta.dir, "TournamentTeamsPage.tsx"), "utf8");

    expect(source).toContain("md:grid-cols-2");
    expect(source).toContain("xl:grid-cols-3");
  });

  it("shows background updates without replacing stale teams", () => {
    const source = readFileSync(join(import.meta.dir, "TournamentTeamsPage.tsx"), "utf8");

    expect(source).toContain("data !== undefined");
    expect(source).not.toContain("if (teams.length === 0)");
    expect(source).toContain('presentation.contentState === "empty"');
    expect(source).toContain("if (presentation.showRefreshError)");
    expect(source).toContain('state="refresh-error"');
    expect(source).toContain("onRetry={() => void teamsQuery.refetch()}");
    expect(source).toContain('t("tournamentDetail.pageState.updating")');
  });
});
