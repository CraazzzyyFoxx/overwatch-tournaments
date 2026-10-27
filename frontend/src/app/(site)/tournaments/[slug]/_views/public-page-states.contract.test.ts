import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import type { Stage } from "@/types/tournament.types";
import { getPublicPageQueryPresentation } from "@/lib/public-page-query-presentation";

type QueryPresentation = {
  initialState: "skeleton" | "error" | null;
  contentState: "empty" | "content" | null;
  showUpdating: boolean;
  showRefreshError: boolean;
};

type GetQueryPresentation = (input: {
  data: unknown;
  itemCount: number;
  isPending: boolean;
  isError: boolean;
  isFetching: boolean;
}) => QueryPresentation;

const heroesModule =
  (await import("./TournamentStatsPage")) as typeof import("./TournamentStatsPage") & {
    getHeroesQueryPresentation?: GetQueryPresentation;
    getHeroPlaytimeMetric?: (playtime: number, leaderPlaytime: number) => {
      sharePercent: number;
      barWidthPercent: number;
    };
  };
const standingsTableModule =
  (await import("../../../../../components/StandingsTable")) as typeof import("../../../../../components/StandingsTable") & {
    getStandingsStagesQueryOptions?: (
      tournamentId: number | undefined,
      providedStages: Stage[] | undefined,
      getStages: (id: number) => Promise<Stage[]>
    ) => { enabled: boolean; queryFn: () => Promise<Stage[]> };
  };

const viewsRoot = import.meta.dirname;
const tournamentRoot = join(viewsRoot, "..");
const componentsRoot = join(viewsRoot, "../../../../../components");

function pageSource(fileName: string) {
  return readFileSync(join(viewsRoot, fileName), "utf8");
}

function routeSource(segment: string) {
  return readFileSync(join(tournamentRoot, segment, "page.tsx"), "utf8");
}

describe("public tournament page query states", () => {
  // Teams used to ship its own near-identical `getTeamsQueryPresentation`
  // (content state named "teams", count named `teamCount`); it now shares this
  // one helper, so it is covered by exactly the same table.
  const presentations: Array<[string, GetQueryPresentation | undefined]> = [
    ["heroes", heroesModule.getHeroesQueryPresentation],
    ["teams", getPublicPageQueryPresentation]
  ];

  for (const [page, present] of presentations) {
    it(`${page} uses its exact skeleton only before data exists`, () => {
      expect(
        present?.({
          data: undefined,
          itemCount: 0,
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

    it(`${page} keeps cached content visible during refresh and stale errors`, () => {
      expect(
        present?.({
          data: { results: [{ id: 1 }] },
          itemCount: 1,
          isPending: false,
          isError: false,
          isFetching: true
        })
      ).toEqual({
        initialState: null,
        contentState: "content",
        showUpdating: true,
        showRefreshError: false
      });

      expect(
        present?.({
          data: { results: [{ id: 1 }] },
          itemCount: 1,
          isPending: false,
          isError: true,
          isFetching: false
        })
      ).toEqual({
        initialState: null,
        contentState: "content",
        showUpdating: false,
        showRefreshError: true
      });
    });

    it(`${page} distinguishes blocking failure and true empty data`, () => {
      expect(
        present?.({
          data: undefined,
          itemCount: 0,
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

      expect(
        present?.({
          data: { results: [] },
          itemCount: 0,
          isPending: false,
          isError: false,
          isFetching: false
        })
      ).toEqual({
        initialState: null,
        contentState: "empty",
        showUpdating: false,
        showRefreshError: false
      });
    });
  }
});

describe("public tournament data interactions", () => {
  it("scales a hero's bar against its column's leader, keeping the exact share finite", () => {
    const metric = heroesModule.getHeroPlaytimeMetric;
    const cases: Array<[number, number, number, number]> = [
      // playtime, leader, share %, bar %
      [0.16, 0.16, 16, 100],
      [0.04, 0.16, 4, 25],
      [0, 0.16, 0, 0],
      [-0.5, 0.16, 0, 0],
      [Number.NaN, 0.16, 0, 0],
      [Number.POSITIVE_INFINITY, 0.16, 0, 0],
      [0.1, 0, 10, 0],
      [1.5, 1.5, 100, 100]
    ];

    for (const [playtime, leader, share, bar] of cases) {
      const result = metric?.(playtime, leader);
      expect(result).toEqual({ sharePercent: share, barWidthPercent: bar });
      expect(Number.isFinite(result?.barWidthPercent)).toBe(true);
    }
  });
});

describe("public tournament data page contracts", () => {
  it("does not execute the table fallback stages request when stages are supplied", async () => {
    let fallbackRequests = 0;
    const options = standingsTableModule.getStandingsStagesQueryOptions?.(72, [], async () => {
      fallbackRequests += 1;
      return [];
    });

    expect(options?.enabled).toBe(false);
    if (options?.enabled) await options.queryFn();
    expect(fallbackRequests).toBe(0);
  });

  it("keeps pages headerless with an accessible section label and exact state components", () => {
    const contracts = [
      ["TournamentEncountersPage.tsx", "TournamentMatchesSkeleton"],
      ["TournamentStatsPage.tsx", "TournamentHeroesSkeleton"],
    ];

    for (const [fileName, skeleton] of contracts) {
      const source = pageSource(fileName);
      // The section nav already names the page; no in-page heading remains,
      // but the landmark keeps an accessible name.
      expect(source).toContain("aria-label={t(");
      expect(source).toContain(skeleton);
      expect(source).toContain('state="initial-error"');
      expect(source).toContain('state="refresh-error"');
      expect(source).toContain('state="empty"');
      expect(source).toContain("onRetry={() => void");
    }
  });

  it("keeps the standings table contained, sticky and semantic", () => {
    const table = readFileSync(join(componentsRoot, "StandingsTable.tsx"), "utf8");

    expect(table).toContain("matches_history");
    expect(table).toContain("team?.group?.name");
    expect(table).toContain('scope="col"');
  });

  it("keeps every route file thin and free from generic loading gates", () => {
    // No `standings`: it was folded into `bracket?view=standings` when the
    // standalone route was removed, so the segment has no page file to read.
    for (const segment of ["matches", "stats", "teams", "participants", "bracket"]) {
      const source = routeSource(segment);
      expect(source).not.toContain("Skeleton");
      expect(source).not.toContain("isLoading");
      expect(source).not.toContain("isPending");
      expect(source).not.toContain("tournamentNotFound");
      expect(source).not.toContain("useTranslations");
      expect(source).not.toContain("PageState");
    }
  });

  it("gives the bracket its own labelled horizontal scroll owner", () => {
    const page = [
      readFileSync(join(tournamentRoot, "bracket", "TournamentBracketPage.tsx"), "utf8"),
      readFileSync(join(tournamentRoot, "bracket", "BracketScroller.tsx"), "utf8")
    ].join("\n");

    // <section> + an accessible name is the region; no explicit role needed.
    expect(page).toContain("<section");
    expect(page).not.toContain('role="region"');
    expect(page).toContain("tabIndex={0}");
    expect(page).toContain('aria-label={t("tournamentDetail.bracketRegion")}');
  });

  it("defines the background-refresh badge exactly once", () => {
    const views = [
      pageSource("TournamentEncountersPage.tsx"),
      pageSource("TournamentStatsPage.tsx"),
      pageSource("TournamentTeamsPage.tsx"),
      readFileSync(join(tournamentRoot, "bracket", "TournamentBracketPage.tsx"), "utf8")
    ];

    for (const source of views) {
      expect(source).toContain("<UpdatingBadge />");
    }
  });

  it("scopes every workspace-aware query with the hydrated tournament workspace", () => {
    const bracketData = readFileSync(join(tournamentRoot, "bracket", "bracketData.ts"), "utf8");
    expect(bracketData).toContain(
      "tournamentQueryKeys.encounters(tournament.id, tournament.workspace_id)"
    );
    expect(
      pageSource("TournamentEncountersPage.tsx") +
        readFileSync(join(process.cwd(), "src/lib/tournament/encounters-query.ts"), "utf8")
    ).toContain("tournament.workspace_id");
  });

  it("keeps the teams grid scoped, responsive and non-destructive during refresh", () => {
    const source = [
      pageSource("TournamentTeamsPage.tsx"),
      readFileSync(join(viewsRoot, "useTournamentTeamsData.ts"), "utf8"),
      readFileSync(join(process.cwd(), "src/lib/tournament/teams-query.ts"), "utf8")
    ].join("\n");

    expect(source).toContain(
      "tournamentQueryKeys.teams(tournament.id, tournament.workspace_id)"
    );
    expect(source).toContain("teamService.getAll({");
    expect(source).toContain("tournamentId: tournament.id");
    expect(source).toContain("workspaceId: tournament.workspace_id");
    expect(source).not.toContain("useSelectedWorkspace");
    expect(source).toContain("md:grid-cols-2");
    expect(source).toContain("xl:grid-cols-3");

    // Stale teams must survive a failed refresh, and a blocking initial error
    // must be checked before the no-content skeleton fallback.
    expect(source).not.toContain("if (teams.length === 0)");
    expect(source).toContain('presentation.contentState === "empty"');
    expect(source).toContain("if (presentation.showRefreshError)");
    expect(source).toContain('state="refresh-error"');
    expect(source).toContain("onRetry={() => void teamsQuery.refetch()}");

    const initialErrorBranch = source.indexOf('presentation.initialState === "error"');
    const skeletonBranch = source.indexOf('presentation.initialState === "skeleton"');
    expect(initialErrorBranch).toBeGreaterThan(-1);
    expect(skeletonBranch).toBeGreaterThan(-1);
    expect(initialErrorBranch).toBeLessThan(skeletonBranch);
  });
});
