import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "bun:test";

import type { Stage, Tournament, TournamentStatus } from "@/types/tournament.types";

import { createBracketQueryPlan, deriveBracketLoadState, isStageReportable, isStageVisibleToViewer } from "./bracketData";

const bracketModule =
  (await import("./TournamentBracketPage")) as typeof import("./TournamentBracketPage") & {
    getBracketRefetchInterval?: (status: TournamentStatus) => number | false;
  };

describe("TournamentBracketPage", () => {
  it("keeps the route wrapper thin and leaves all bracket data ownership to the page", () => {
    const routeSource = readFileSync(join(import.meta.dir, "page.tsx"), "utf8");

    expect(routeSource).not.toContain("useTournamentStagesQuery");
    expect(routeSource).not.toContain('from "@/components/ui/skeleton"');
    expect(routeSource).not.toContain("BracketPageSkeleton");
    expect(routeSource).not.toContain("stagesQuery.data ?? []");
    expect(routeSource).not.toContain("stages={");
  });

  it("mounts tournament invalidation once from the shared client tournament layout", () => {
    const layoutSource = readFileSync(join(import.meta.dir, "../layout.tsx"), "utf8");
    const clientLayoutSource = readFileSync(
      join(import.meta.dir, "../_components/TournamentClientLayout.tsx"),
      "utf8"
    );

    expect(layoutSource).toContain("TournamentClientLayout");
    expect(layoutSource).toContain("slug={resolvedParams.slug}");
    expect(clientLayoutSource).toContain("useInvalidation({");
    expect(clientLayoutSource).toContain("workspaceId: tournament?.workspace_id");
  });

  it("filters playoff standings by the active stage before rendering", () => {
    const source = readFileSync(join(import.meta.dir, "TournamentBracketPage.tsx"), "utf8");

    expect(source).toContain("const stagePlayoffStandings = playoffStandings.filter(");
    expect(source).toContain("standing.stage_id === stage.id");
  });

  it.each([
    ["live", 15_000],
    ["playoffs", 15_000],
    ["registration", false],
    ["draft", false],
    ["check_in", false],
    ["completed", false],
    ["archived", false]
  ] as const)("uses the lifecycle polling policy for %s", (status, expected) => {
    expect(bracketModule.getBracketRefetchInterval?.(status)).toBe(expected);
  });

  it("uses canonical concurrent bracket queries with full standings data", () => {
    const source = readFileSync(join(import.meta.dir, "bracketData.ts"), "utf8");

    expect(source).toContain("tournamentQueryKeys.encounters(");
    expect(source).toContain("tournamentQueryKeys.bracketStandings(");
    expect(source).toContain("workspaceId: tournament.workspace_id");
    expect(source).toContain("includeMatchesHistory: true");
    expect(source).toContain("includeTeamGroup: true");
    expect(source).toContain(
      "const refetchInterval = getBracketRefetchInterval(tournament.status)"
    );
    expect(source).toContain("refetchInterval,");
    expect(source).toContain("refetchIntervalInBackground: false");
    expect(source).toContain("enabled: hasTournament && hasStage");
  });

  it("starts stages, encounters and standings together from a hydrated stage summary", () => {
    const tournament = {
      id: 72,
      workspace_id: 9,
      status: "live",
      stages: [
        {
          id: 301,
          tournament_id: 72,
          name: "Playoffs",
          stage_type: "single_elimination",
          is_active: true,
          is_completed: false,
          order: 1
        }
      ]
    } as Tournament;

    const plan = createBracketQueryPlan(tournament, null);

    expect(plan.initialStageId).toBe(301);
    expect(plan.stages.enabled).toBe(true);
    expect(plan.encounters.enabled).toBe(true);
    expect(plan.standings.enabled).toBe(true);
    expect(plan.stages.queryKey).toEqual(["tournament", 72, "stages"]);
    expect(plan.encounters.queryKey).toEqual(["encounters", "tournament", 72, 9]);
    expect(plan.standings.queryKey).toEqual(["standings", 72, "bracket", 9]);
  });

  it("does not plan an encounters request until a real stage id exists", () => {
    const tournament = {
      id: 72,
      workspace_id: 9,
      status: "completed",
      stages: []
    } as unknown as Tournament;

    const plan = createBracketQueryPlan(tournament, null);

    expect(plan.initialStageId).toBeNull();
    expect(plan.stages.enabled).toBe(true);
    expect(plan.encounters.enabled).toBe(false);
    expect(plan.standings.enabled).toBe(false);
  });

  it("reconciles a stale summary selection against the loaded stage structure", () => {
    const tournament = {
      id: 72,
      workspace_id: 9,
      status: "live",
      stages: [{ id: 301, is_active: true, stage_type: "single_elimination" }]
    } as Tournament;
    const fullStages = [
      {
        id: 302,
        is_active: true,
        stage_type: "double_elimination",
        items: []
      }
    ] as unknown as Stage[];

    const summaryPlan = createBracketQueryPlan(tournament, "301");
    const reconciledPlan = createBracketQueryPlan(tournament, "301", fullStages);

    expect(summaryPlan.initialStageId).toBe(301);
    expect(reconciledPlan.initialStageId).toBe(302);
    expect(reconciledPlan.encounters.enabled).toBe(true);
  });

  it("distinguishes initial stages failure, initial loading and stale refresh states", () => {
    const initialStagesError = deriveBracketLoadState({
      hasStageId: true,
      stages: { hasData: false, isPending: false, isError: true, isFetching: false },
      encounters: { hasData: false, isPending: true, isError: false, isFetching: false },
      standings: { hasData: false, isPending: true, isError: false, isFetching: false }
    });
    const initialNoData = deriveBracketLoadState({
      hasStageId: true,
      stages: { hasData: false, isPending: true, isError: false, isFetching: true },
      encounters: { hasData: false, isPending: true, isError: false, isFetching: true },
      standings: { hasData: false, isPending: true, isError: false, isFetching: true }
    });
    const staleRefreshError = deriveBracketLoadState({
      hasStageId: true,
      stages: { hasData: true, isPending: false, isError: true, isFetching: false },
      encounters: { hasData: true, isPending: false, isError: false, isFetching: false },
      standings: { hasData: true, isPending: false, isError: false, isFetching: false }
    });
    const staleUpdating = deriveBracketLoadState({
      hasStageId: true,
      stages: { hasData: true, isPending: false, isError: false, isFetching: true },
      encounters: { hasData: true, isPending: false, isError: false, isFetching: true },
      standings: { hasData: true, isPending: false, isError: false, isFetching: false }
    });

    expect(initialStagesError.kind).toBe("initial-error");
    expect(initialNoData.kind).toBe("initial-loading");
    expect(staleRefreshError.kind).toBe("refresh-error");
    expect(staleUpdating).toEqual({ kind: "ready", isUpdating: true });
  });

  it("keeps stale bracket content visible during refreshes and errors", () => {
    const source = readFileSync(join(import.meta.dir, "TournamentBracketPage.tsx"), "utf8");

    expect(source).toContain("deriveBracketLoadState({");
    expect(source).toContain('state="initial-error"');
    expect(source).toContain('state="refresh-error"');
    expect(source).toContain("[stagesQuery.refetch()]");
    expect(source).toContain("requests.push(encountersQuery.refetch(), standingsQuery.refetch())");
    expect(source).toContain("loadState.isUpdating");
    // The badge markup itself now lives in the one shared `UpdatingBadge`.
    expect(source).toContain("<UpdatingBadge />");
  });
});

  describe("isStageVisibleToViewer", () => {
    const base = {
      id: 1,
      tournament_id: 72,
      name: "Playoffs",
      stage_type: "single_elimination",
      is_active: false,
      order: 1
    };

    it("hides an organizer's un-activated preview from a spectator", () => {
      const preview = { ...base, is_published: false, is_completed: false } as Stage;
      expect(isStageVisibleToViewer(preview, false)).toBe(false);
    });

    it("shows the same preview to an admin", () => {
      const preview = { ...base, is_published: false, is_completed: false } as Stage;
      expect(isStageVisibleToViewer(preview, true)).toBe(true);
    });

    it("shows a published stage to everyone", () => {
      const published = { ...base, is_published: true, is_completed: false } as Stage;
      expect(isStageVisibleToViewer(published, false)).toBe(true);
    });

    it("shows a completed stage to everyone even if never explicitly published", () => {
      const completed = { ...base, is_published: false, is_completed: true } as Stage;
      expect(isStageVisibleToViewer(completed, false)).toBe(true);
    });
  });

  describe("isStageReportable", () => {
    it("blocks a report for an un-activated preview stage", () => {
      const preview = { is_published: false, is_completed: false } as Stage;
      expect(isStageReportable(preview)).toBe(false);
    });

    it("allows a report once the stage is published", () => {
      const published = { is_published: true, is_completed: false } as Stage;
      expect(isStageReportable(published)).toBe(true);
    });

    it("allows a report for a completed stage", () => {
      const completed = { is_published: false, is_completed: true } as Stage;
      expect(isStageReportable(completed)).toBe(true);
    });

    it("defaults to reportable when the stage is not resolved (scrim encounter, no stage)", () => {
      expect(isStageReportable(undefined)).toBe(true);
    });
  });
