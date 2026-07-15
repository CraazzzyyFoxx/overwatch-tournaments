import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "bun:test";

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

const encountersModule =
  (await import("../../../../../components/EncountersTable")) as typeof import("../../../../../components/EncountersTable") & {
    getEncountersQueryPresentation?: GetQueryPresentation;
  };
const heroesModule =
  (await import("./TournamentHeroPlaytimePage")) as typeof import("./TournamentHeroPlaytimePage") & {
    getHeroesQueryPresentation?: GetQueryPresentation;
  };
const standingsModule =
  (await import("./TournamentStandingsPage")) as typeof import("./TournamentStandingsPage") & {
    getStandingsQueryPresentation?: GetQueryPresentation;
  };

const pagesRoot = import.meta.dir;
const tournamentRoot = join(pagesRoot, "..");
const componentsRoot = join(pagesRoot, "../../../../../components");

function pageSource(fileName: string) {
  return readFileSync(join(pagesRoot, fileName), "utf8");
}

function routeSource(segment: string) {
  return readFileSync(join(tournamentRoot, segment, "page.tsx"), "utf8");
}

describe("public tournament page query states", () => {
  const presentations: Array<[string, GetQueryPresentation | undefined]> = [
    ["matches", encountersModule.getEncountersQueryPresentation],
    ["heroes", heroesModule.getHeroesQueryPresentation],
    ["standings", standingsModule.getStandingsQueryPresentation]
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

describe("public tournament data page contracts", () => {
  it("gives every page the shared editorial heading and exact state components", () => {
    const contracts = [
      ["TournamentEncountersPage.tsx", "TournamentMatchesSkeleton"],
      ["TournamentHeroPlaytimePage.tsx", "TournamentHeroesSkeleton"],
      ["TournamentStandingsPage.tsx", "TournamentStandingsSkeleton"]
    ];

    for (const [fileName, skeleton] of contracts) {
      const source = pageSource(fileName);
      expect(source).toContain("styles.pageEyebrow");
      expect(source).toContain("styles.pageHeading");
      expect(source).toContain("styles.pageTitle");
      expect(source).toContain(skeleton);
      expect(source).toContain('state="initial-error"');
      expect(source).toContain('state="refresh-error"');
      expect(source).toContain('state="empty"');
      expect(source).toContain("onRetry={() => void");
    }
  });

  it("keeps matches on the supported 15-row server page and URL search contract", () => {
    const table = readFileSync(join(componentsRoot, "EncountersTable.tsx"), "utf8");

    expect(table).toContain("const PER_PAGE = 15");
    expect(table).toContain("encounterService.getAll(");
    expect(table).toContain("new URLSearchParams(window.location.search)");
    expect(table).toContain('params.set("search"');
    expect(table).toContain('params.set("page"');
    expect(table).not.toMatch(/statusFilter|status_filter|status:\s/);
    expect(table).not.toContain("setSearchValue(search)");
    expect(table).toContain("searchInputRef");
    expect(table).toContain("nextSearch");
  });

  it("keeps hero role controls and exposes ranked quantitative bars", () => {
    const source = pageSource("TournamentHeroPlaytimePage.tsx");

    expect(source).toContain("ROLE_ORDER");
    expect(source).toContain('roleFilter === "all"');
    expect(source).toContain("aria-pressed");
    expect(source).toContain("aria-label={");
    expect(source).toContain('role="progressbar"');
    expect(source).toContain("aria-valuenow");
    expect(source).toContain("data-rank");
    expect(source).toContain("maxPlaytime > 0");
  });

  it("keeps rich standings data and a contained, sticky semantic table", () => {
    const page = pageSource("TournamentStandingsPage.tsx");
    const table = readFileSync(join(componentsRoot, "StandingsTable.tsx"), "utf8");

    expect(page).toContain("tournamentService.getStandings(");
    expect(page).toContain("tournament.workspace_id");
    expect(page).not.toContain("getBracketStandings");
    expect(table).toContain("matches_history");
    expect(table).toContain("team?.group?.name");
    expect(table).toContain("styles.standingsViewport");
    expect(table).toContain("styles.stickyTeamColumn");
    expect(table).toContain('<th scope="col"');
    expect(page).toContain("styles.stageEmpty");
  });

  it("keeps route files thin and free from generic loading gates", () => {
    for (const segment of ["matches", "heroes", "standings"]) {
      const source = routeSource(segment);
      expect(source).not.toContain("Skeleton");
      expect(source).not.toContain("isLoading");
      expect(source).not.toContain("tournamentNotFound");
      expect(source).not.toContain("useTranslations");
    }
  });

  it("contains page width and horizontal table overflow at 360px", () => {
    const css = readFileSync(join(tournamentRoot, "TournamentDetail.module.css"), "utf8");

    expect(css).toMatch(/\.publicDataPage\s*\{[\s\S]*?min-width:\s*0/);
    expect(css).toMatch(/\.tableViewport\s*\{[\s\S]*?overflow-x:\s*auto/);
    expect(css).toMatch(/\.standingsViewport\s*\{[\s\S]*?overflow-x:\s*auto/);
    expect(css).toMatch(/\.stickyTeamColumn\s*\{[\s\S]*?position:\s*sticky/);
    expect(css).toContain("@media (max-width: 640px)");
  });
});
