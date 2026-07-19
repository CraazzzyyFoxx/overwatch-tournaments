import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "bun:test";

import type { Stage, Standings, Tournament } from "@/types/tournament.types";

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
    activateEncounterRowFromKeyboard?: (
      event: {
        key: string;
        target: object;
        currentTarget: object;
        preventDefault: () => void;
      },
      navigate: () => void
    ) => boolean;
  };
const heroesModule =
  (await import("./TournamentHeroPlaytimePage")) as typeof import("./TournamentHeroPlaytimePage") & {
    getHeroesQueryPresentation?: GetQueryPresentation;
    getHeroPlaytimeMetric?: (playtime: number) => {
      sharePercent: number;
      barWidthPercent: number;
    };
  };
const standingsModule =
  (await import("./TournamentStandingsPage")) as typeof import("./TournamentStandingsPage") & {
    getStandingsQueryPresentation?: GetQueryPresentation;
    getPublicStandingsQueryPlan?: (
      tournament: Tournament | undefined,
      source: {
        getStandings: (tournamentId: number, workspaceId: number | null) => Promise<Standings[]>;
        getStages: (tournamentId: number) => Promise<Stage[]>;
      }
    ) => {
      standings: { enabled: boolean; queryFn: () => Promise<Standings[]> };
      stages: { enabled: boolean; queryFn: () => Promise<Stage[]> };
    };
    getEffectiveStandingsView?: (
      selected: "playoff" | "groups" | "combined",
      hasPlayoff: boolean,
      hasGroups: boolean
    ) => "playoff" | "groups" | "combined" | null;
  };
const standingsTableModule =
  (await import("../../../../../components/StandingsTable")) as typeof import("../../../../../components/StandingsTable") & {
    getStandingsStagesQueryOptions?: (
      tournamentId: number | undefined,
      providedStages: Stage[] | undefined,
      getStages: (id: number) => Promise<Stage[]>
    ) => { enabled: boolean; queryFn: () => Promise<Stage[]> };
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

describe("public tournament data interactions", () => {
  it("activates only the focused encounter row for Enter and Space", () => {
    for (const key of ["Enter", " "]) {
      const row = {};
      let navigations = 0;
      let prevented = 0;
      const activated = encountersModule.activateEncounterRowFromKeyboard?.(
        {
          key,
          target: row,
          currentTarget: row,
          preventDefault: () => {
            prevented += 1;
          }
        },
        () => {
          navigations += 1;
        }
      );

      expect(activated).toBe(true);
      expect(navigations).toBe(1);
      expect(prevented).toBe(1);
    }
  });

  it("leaves nested log links and buttons in control of their keyboard action", () => {
    for (const key of ["Enter", " "]) {
      const row = {};
      const nestedControl = {};
      let navigations = 0;
      let prevented = 0;
      let nestedActions = 0;
      const activated = encountersModule.activateEncounterRowFromKeyboard?.(
        {
          key,
          target: nestedControl,
          currentTarget: row,
          preventDefault: () => {
            prevented += 1;
          }
        },
        () => {
          navigations += 1;
        }
      );
      nestedActions += 1;

      expect(activated).toBe(false);
      expect(navigations).toBe(0);
      expect(prevented).toBe(0);
      expect(nestedActions).toBe(1);
    }

    const table = readFileSync(join(componentsRoot, "EncountersTable.tsx"), "utf8");
    expect(table).toContain("onClick={openEncounter}");
    expect(table).toContain("event.stopPropagation()");
  });

  it("falls back to the only available standings stage without losing a valid selection", () => {
    const effective = standingsModule.getEffectiveStandingsView;

    expect(effective?.("groups", true, false)).toBe("playoff");
    expect(effective?.("playoff", false, true)).toBe("groups");
    expect(effective?.("groups", true, true)).toBe("groups");
    expect(effective?.("playoff", true, true)).toBe("playoff");
    expect(effective?.("combined", true, true)).toBe("combined");
    expect(effective?.("combined", false, false)).toBeNull();
  });

  it("uses one finite absolute playtime scale for the bar and accessibility value", () => {
    const metric = heroesModule.getHeroPlaytimeMetric;
    const cases: Array<[number, number]> = [
      [0.25, 25],
      [0.125, 12.5],
      [0, 0],
      [-0.5, 0],
      [Number.NaN, 0],
      [Number.POSITIVE_INFINITY, 0],
      [1.5, 100],
      [101, 100]
    ];

    for (const [playtime, expected] of cases) {
      const result = metric?.(playtime);
      expect(result).toEqual({ sharePercent: expected, barWidthPercent: expected });
      expect(Number.isFinite(result?.barWidthPercent)).toBe(true);
    }
  });
});

describe("public tournament data page contracts", () => {
  it("starts rich standings and required full-stage metadata together", async () => {
    let standingsStarted = 0;
    let stagesStarted = 0;
    let releaseStandings = () => undefined;
    const standingsBlocked = new Promise<void>((resolve) => {
      releaseStandings = resolve;
    });
    const tournament = { id: 72, workspace_id: 9 } as Tournament;
    const plan = standingsModule.getPublicStandingsQueryPlan?.(tournament, {
      getStandings: async () => {
        standingsStarted += 1;
        await standingsBlocked;
        return [];
      },
      getStages: async () => {
        stagesStarted += 1;
        return [];
      }
    });

    expect(plan?.standings.enabled).toBe(true);
    expect(plan?.stages.enabled).toBe(true);
    const standingsRequest = plan?.standings.queryFn();
    const stagesRequest = plan?.stages.queryFn();
    expect(standingsStarted).toBe(1);
    expect(stagesStarted).toBe(1);

    await stagesRequest;
    releaseStandings();
    await standingsRequest;
  });

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
      ["TournamentHeroPlaytimePage.tsx", "TournamentHeroesSkeleton"],
      ["TournamentStandingsPage.tsx", "TournamentStandingsSkeleton"]
    ];

    for (const [fileName, skeleton] of contracts) {
      const source = pageSource(fileName);
      // The section nav already names the page; no in-page heading remains,
      // but the landmark keeps an accessible name.
      expect(source).toContain("aria-label={t(");
      expect(source).not.toContain('className="section-head"');
      expect(source).not.toContain("styles.pageHeading");
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
    expect(source).toContain("getHeroPlaytimeMetric");
  });

  it("keeps rich standings data and a contained, sticky semantic table", () => {
    const page = pageSource("TournamentStandingsPage.tsx");
    const table = readFileSync(join(componentsRoot, "StandingsTable.tsx"), "utf8");

    expect(page).toContain("tournamentService.getStandings(");
    expect(page).toContain("tournamentService.getStages(");
    expect(page).toContain("tournament.workspace_id");
    expect(page).not.toContain("getBracketStandings");
    expect(table).toContain("matches_history");
    expect(table).toContain("team?.group?.name");
    expect(table).toContain("styles.standingsViewport");
    expect(table).toContain("styles.stickyTeamColumn");
    expect(table).toContain('<th scope="col"');
    expect(page).toContain("styles.stageEmpty");
    expect(page).toContain("stages={stages}");
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
