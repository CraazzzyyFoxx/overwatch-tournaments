import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HydrationBoundary, type DehydratedState } from "@tanstack/react-query";
import { isValidElement, Suspense, type ReactElement } from "react";

import { ApiError } from "@/lib/api/error";
import { ffaStageQueryOptions } from "@/lib/tournament/ffa-stage-query";
import { mapPoolConfigsQueryOptions } from "@/lib/tournament/map-pool-query";
import { tournamentOverviewQueryOptions } from "@/lib/tournament/overview-query";
import { tournamentRegistrationFormQueryOptions } from "@/lib/tournament/registrations-query";
import encounterService from "@/services/encounter.service";
import ffaService from "@/services/ffa.service";
import pickBanService from "@/services/pickBan.service";
import registrationService from "@/services/registration.service";
import streamService from "@/services/stream.service";
import tournamentService from "@/services/tournament.service";
import type { StageSummary, Tournament } from "@/types/tournament.types";

import TournamentOverviewBoundary from "./TournamentOverviewBoundary";
import { TournamentShellSkeleton } from "./_components/TournamentSkeletons";
import { tournamentStreamsQueryOptions } from "./_queries/tournamentStreams";
import { createBracketQueryPlan } from "./bracket/bracketData";

vi.mock("next-intl/server", () => ({
  getTranslations: async () => (key: string) => key
}));
// The factory has to cover every name the graph under `./layout` imports from
// `next-intl`, not just the ones this file exercises: a `mock.module` replaces
// the module wholesale, so a missing export is an ESM link error at import time
// ("Export named 'useFormatter' not found"), which takes the whole FILE down
// before any test runs. `useFormatter` arrives via the shell's phase strip
// (`_components/PhaseTimeline.tsx`, `_components/NextPhaseChip.tsx`).
vi.mock("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => (key: string) => key
}));
vi.mock("@/lib/datetime/client", () => ({
  useFormatter: () => ({
    dateTime: () => "",
    relativeTime: () => ""
  })
}));
vi.mock("@/lib/site/metadata", () => ({
  resolveSiteMetadata: async () => ({ name: "Test OWT", origin: "https://example.test" })
}));

const { default: TournamentLayout, generateMetadata } = await import("./layout");

const overviewFixture: Tournament = {
  id: 72,
  created_at: new Date("2026-01-01T00:00:00Z"),
  updated_at: null,
  workspace_id: 4,
  name: "Summer Clash",
  slug: "summer-clash",
  start_date: new Date("2026-07-15T12:00:00Z"),
  end_date: new Date("2026-07-16T12:00:00Z"),
  description: "Public tournament",
  challonge_id: null,
  challonge_slug: null,
  is_league: false,
  is_finished: false,
  is_hidden: false,
  team_formation: "balancer",
  status: "live",
  auto_transitions_enabled: true,
  allow_late_registration: false,
  phase_schedule: [],
  win_points: 3,
  draw_points: 1,
  loss_points: 0,
  stages: [],
  participants_count: 84,
  registrations_count: 96,
  teams_count: 12,
  division_grid_version_id: null,
  division_grid_version: null
};

const paramsFor = (slug: string) => Promise.resolve({ slug });
const afterTurn = () => new Promise<void>((resolve) => setTimeout(resolve, 20));
// A legacy numeric id and an old/retired slug both reach the backend exactly
// like a current slug -- the URL segment carries no format the frontend must
// validate anymore (see resolve_public_ref). These stand in for "whatever the
// viewer's URL happens to carry".
const arbitraryRefs = ["summer-clash", "72", "old-retired-slug", "summer-clash-2"];

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

beforeEach(() => {
  vi.spyOn(registrationService, "getForm").mockResolvedValue(null);
  vi.spyOn(pickBanService, "listPublicConfigs").mockResolvedValue({ configs: [] });
  vi.spyOn(streamService, "getTournamentStreams").mockResolvedValue({
    official: [],
    participants: []
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("TournamentLayout streaming overview", () => {
  it("renders the client shell inside the overview seed, without awaiting the overview itself", async () => {
    const pendingOverview = deferred<Tournament>();
    const overviewSpy = vi
      .spyOn(tournamentService, "getPublicOverview")
      .mockReturnValue(pendingOverview.promise);
    const layoutPromise = TournamentLayout({ children: null, params: paramsFor("summer-clash") });

    const firstResult = await Promise.race([
      layoutPromise.then((result) => ({ kind: "layout" as const, result })),
      afterTurn().then(() => ({ kind: "waiting" as const }))
    ]);

    if (firstResult.kind === "waiting") {
      pendingOverview.resolve(overviewFixture);
      await layoutPromise;
    }

    expect(firstResult.kind).toBe("layout");
    if (firstResult.kind !== "layout") return;
    expect(firstResult.result.type).toBe(Suspense);
    const suspenseProps = firstResult.result.props as {
      fallback: ReactElement;
      children: ReactElement;
    };
    const overviewBoundaryEl = suspenseProps.children;
    // The whole point of the boundary: the layout hands back its tree without
    // ever touching the overview itself, so the document streams immediately.
    expect(overviewSpy).not.toHaveBeenCalled();
    // The shell is the seed's CHILD. As a sibling the server rendered it before
    // the seed resolved — an empty, pending query — while the browser rendered
    // it from the seed: a hydration mismatch on every cache-missing visit.
    expect(overviewBoundaryEl.type).toBe(TournamentOverviewBoundary);
    const clientLayoutEl = (overviewBoundaryEl.props as { children: ReactElement }).children;
    expect((clientLayoutEl.props as { children: unknown }).children).toBeNull();
    // Nothing can paint before the overview resolves (the tab below awaits the
    // same read), so the fallback is the shell's own skeleton rather than a
    // blank — streamed by the server instead of appearing after hydration.
    expect(suspenseProps.fallback.type).toBe(TournamentShellSkeleton);
    // Both the boundary and the client shell resolve the SAME URL segment --
    // neither pre-parses or coerces it.
    expect((overviewBoundaryEl.props as { slug: unknown }).slug).toBe("summer-clash");
    expect((clientLayoutEl.props as { slug: unknown }).slug).toBe("summer-clash");

    const boundaryPromise = TournamentOverviewBoundary(
      overviewBoundaryEl.props as Parameters<typeof TournamentOverviewBoundary>[0]
    );
    const boundaryBeforeOverview = await Promise.race([
      boundaryPromise.then(() => "resolved" as const),
      afterTurn().then(() => "waiting" as const)
    ]);

    expect(overviewSpy).toHaveBeenCalledTimes(1);
    expect(overviewSpy).toHaveBeenCalledWith("summer-clash");
    expect(boundaryBeforeOverview).toBe("waiting");

    pendingOverview.resolve(overviewFixture);
    const hydrated = await boundaryPromise;
    expect(isValidElement(hydrated)).toBe(true);
    if (!isValidElement(hydrated)) throw new Error("Expected hydrated overview element");
    expect(hydrated.type).toBe(HydrationBoundary);
    expect((hydrated.props as { children: unknown }).children).toBe(clientLayoutEl);
  });

  it("uses intentional streamed notFound control flow for an API 404", async () => {
    const overviewSpy = vi
      .spyOn(tournamentService, "getPublicOverview")
      .mockRejectedValue(new ApiError(404, [{ msg: "Tournament not found", code: "not_found" }]));

    let thrown: unknown;
    try {
      await TournamentOverviewBoundary({ slug: "missing-tournament", children: null });
    } catch (error) {
      thrown = error;
    }

    expect(overviewSpy).toHaveBeenCalledTimes(1);
    expect(thrown).toMatchObject({ digest: "NEXT_HTTP_ERROR_FALLBACK;404" });
  });

  it("renders the shell unseeded for a non-404 overview failure, deferring to its own retry", async () => {
    const overviewSpy = vi
      .spyOn(tournamentService, "getPublicOverview")
      .mockRejectedValue(new Error("upstream unavailable"));
    const shell = <div data-shell />;

    const result = await TournamentOverviewBoundary({ slug: "summer-clash", children: shell });

    expect(overviewSpy).toHaveBeenCalledTimes(1);
    expect(result).toBe(shell);
  });

  it("hydrates a successful overview with every read the shell makes", async () => {
    const overviewSpy = vi
      .spyOn(tournamentService, "getPublicOverview")
      .mockResolvedValue(overviewFixture);

    const result = await TournamentOverviewBoundary({ slug: "summer-clash", children: null });

    expect(overviewSpy).toHaveBeenCalledTimes(1);
    expect(isValidElement(result)).toBe(true);
    if (!isValidElement(result)) throw new Error("Expected a React element");
    expect(result.type).toBe(HydrationBoundary);
    // An unseeded shell read is created empty before the tab below resolves,
    // and fetched in the browser before that tab hydrates: the tab then renders
    // data the server never had. A live tournament's shell reads all four.
    const seeded = (result.props as { state: DehydratedState }).state.queries.map(
      (query) => query.queryKey
    );
    expect(seeded).toEqual(
      expect.arrayContaining([
        tournamentOverviewQueryOptions("summer-clash").queryKey,
        mapPoolConfigsQueryOptions(overviewFixture.id).queryKey,
        tournamentRegistrationFormQueryOptions(overviewFixture).queryKey,
        tournamentStreamsQueryOptions(overviewFixture.id).queryKey
      ])
    );
  });

  it("seeds the hero's played count while it is played: the encounters and every FFA stage's lobbies", async () => {
    // The overview below reads the same entries; unseeded, the shell created them empty before the overview's own
    // boundary ran, so the server drew the overview's skeleton while the browser — whose shell had fetched them by
    // then — drew its content.
    const stage = (
      id: number,
      stage_type: StageSummary["stage_type"],
      order: number
    ): StageSummary => ({
      id,
      tournament_id: overviewFixture.id,
      name: `Stage ${id}`,
      description: null,
      stage_type,
      max_rounds: 2,
      advance_count: null,
      advance_upper_count: null,
      order,
      is_active: true,
      is_published: true,
      is_completed: false,
      ranking_preset: null,
      tiebreak_order: null,
      scoring: {
        win: null,
        draw: null,
        loss: null,
        preset: null,
        columns: null,
        placement_points: null,
        formula: null
      },
      swiss_bye_points: null,
      swiss_qualify_wins: null,
      swiss_eliminate_losses: null,
      de_grand_final_type: "no_reset",
      seed_ranking: "slot",
      best_of: {
        default: 3,
        by_round: {},
        final: null,
        swiss_qualify: null,
        swiss_eliminate: null
      },
      has_custom_bracket: false,
      challonge_id: null,
      challonge_slug: null
    });
    const live = {
      ...overviewFixture,
      stages: [stage(5, "ffa_league", 1), stage(6, "single_elimination", 2)]
    };
    vi.spyOn(tournamentService, "getPublicOverview").mockResolvedValue(live);
    vi.spyOn(encounterService, "getAll").mockResolvedValue({
      results: [],
      total: 0,
      page: 1,
      per_page: -1
    });
    vi.spyOn(ffaService, "getStage").mockResolvedValue([]);

    const result = await TournamentOverviewBoundary({ slug: "summer-clash", children: null });

    if (!isValidElement(result)) throw new Error("Expected a React element");
    const seeded = (result.props as { state: DehydratedState }).state.queries.map(
      (query) => query.queryKey
    );
    expect(seeded).toEqual(
      expect.arrayContaining([
        createBracketQueryPlan(live, null).encounters.queryKey,
        ffaStageQueryOptions(live.id, 5).queryKey
      ])
    );
  });

  // The URL segment carries no format the layout itself must validate:
  // resolve_public_ref accepts a current slug, a legacy numeric id, or a
  // retired slug identically, so a mismatch (or a stale link) surfaces as an
  // ordinary 404 from the boundary's own overview fetch -- never a
  // synchronous rejection before that fetch runs.
  for (const ref of arbitraryRefs) {
    it(`passes ref ${ref} straight through to the outer shell without blocking on the overview`, async () => {
      const overviewSpy = vi
        .spyOn(tournamentService, "getPublicOverview")
        .mockResolvedValue(overviewFixture);

      const result = await TournamentLayout({ children: null, params: paramsFor(ref) });

      expect(result.type).toBe(Suspense);
      expect(overviewSpy).not.toHaveBeenCalled();
    });
  }

  it("resolves metadata from whatever ref the overview accepts, falling back only on failure", async () => {
    vi.spyOn(tournamentService, "getPublicOverview").mockResolvedValue(overviewFixture);

    const metadata = await generateMetadata({ params: paramsFor("summer-clash") });

    expect(metadata.title).toBe("tournamentDetail.metaTitle | Test OWT");
  });

  it("falls back to generic metadata when the overview ref does not resolve", async () => {
    const overviewSpy = vi
      .spyOn(tournamentService, "getPublicOverview")
      .mockRejectedValue(new ApiError(404, [{ msg: "Tournament not found", code: "not_found" }]));

    const metadata = await generateMetadata({ params: paramsFor("missing-tournament") });

    expect(overviewSpy).toHaveBeenCalledTimes(1);
    expect(metadata.title).toBe("tournamentDetail.metaTitleFallback | Test OWT");
  });
});
