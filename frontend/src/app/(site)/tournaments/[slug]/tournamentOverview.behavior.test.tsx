import { afterEach, describe, expect, it, mock, spyOn } from "bun:test";
import { HydrationBoundary } from "@tanstack/react-query";
import { Fragment, isValidElement, Suspense, type ReactElement } from "react";

import { ApiError } from "@/lib/api/error";
import tournamentService from "@/services/tournament.service";
import type { Tournament } from "@/types/tournament.types";

import TournamentOverviewBoundary from "./TournamentOverviewBoundary";

mock.module("next-intl/server", () => ({
  getTranslations: async () => (key: string) => key
}));
// The factory has to cover every name the graph under `./layout` imports from
// `next-intl`, not just the ones this file exercises: a `mock.module` replaces
// the module wholesale, so a missing export is an ESM link error at import time
// ("Export named 'useFormatter' not found"), which takes the whole FILE down
// before any test runs. `useFormatter` arrives via the shell's phase strip
// (`_components/PhaseTimeline.tsx`, `_components/NextPhaseChip.tsx`).
mock.module("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => (key: string) => key,
  useFormatter: () => ({
    dateTime: () => "",
    relativeTime: () => ""
  })
}));
mock.module("@/lib/site/metadata", () => ({
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

afterEach(() => {
  (tournamentService.getPublicOverview as { mockRestore?: () => void }).mockRestore?.();
});

describe("TournamentLayout streaming overview", () => {
  it("keeps the overview hydration boundary decoupled from the client shell while unresolved", async () => {
    const pendingOverview = deferred<Tournament>();
    const overviewSpy = spyOn(tournamentService, "getPublicOverview").mockReturnValue(
      pendingOverview.promise
    );
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
    expect(firstResult.result.type).toBe(Fragment);
    const [suspenseEl, clientLayoutEl] = (
      firstResult.result.props as { children: ReactElement[] }
    ).children;
    expect(suspenseEl.type).toBe(Suspense);
    const suspenseProps = suspenseEl.props as { fallback: unknown; children: ReactElement };
    // A re-suspended overview fetch must never blank/replace the client shell,
    // so the Suspense carries no fallback of its own.
    expect(suspenseProps.fallback).toBeNull();
    expect(overviewSpy).not.toHaveBeenCalled();
    // TournamentClientLayout is a sibling of the Suspense, not wrapped by it.
    expect(clientLayoutEl.type).not.toBe(Suspense);
    expect((clientLayoutEl.props as { children: unknown }).children).toBeNull();
    // Both the boundary and the client shell resolve the SAME URL segment --
    // neither pre-parses or coerces it.
    expect((clientLayoutEl.props as { slug: unknown }).slug).toBe("summer-clash");

    const boundaryPromise = TournamentOverviewBoundary(
      suspenseProps.children.props as Parameters<typeof TournamentOverviewBoundary>[0]
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
  });

  it("uses intentional streamed notFound control flow for an API 404", async () => {
    const overviewSpy = spyOn(tournamentService, "getPublicOverview").mockRejectedValue(
      new ApiError(404, [{ msg: "Tournament not found", code: "not_found" }])
    );

    let thrown: unknown;
    try {
      await TournamentOverviewBoundary({ slug: "missing-tournament" });
    } catch (error) {
      thrown = error;
    }

    expect(overviewSpy).toHaveBeenCalledTimes(1);
    expect(thrown).toMatchObject({ digest: "NEXT_HTTP_ERROR_FALLBACK;404" });
  });

  it("returns nothing for a non-404 overview failure, deferring to the client shell's own retry", async () => {
    const overviewSpy = spyOn(tournamentService, "getPublicOverview").mockRejectedValue(
      new Error("upstream unavailable")
    );

    const result = await TournamentOverviewBoundary({ slug: "summer-clash" });

    expect(overviewSpy).toHaveBeenCalledTimes(1);
    expect(result).toBeNull();
  });

  it("hydrates a successful overview after the boundary resolves", async () => {
    const overviewSpy = spyOn(tournamentService, "getPublicOverview").mockResolvedValue(
      overviewFixture
    );

    const result = await TournamentOverviewBoundary({ slug: "summer-clash" });

    expect(overviewSpy).toHaveBeenCalledTimes(1);
    expect(isValidElement(result)).toBe(true);
    if (!isValidElement(result)) throw new Error("Expected a React element");
    expect(result.type).toBe(HydrationBoundary);
  });

  // The URL segment carries no format the layout itself must validate:
  // resolve_public_ref accepts a current slug, a legacy numeric id, or a
  // retired slug identically, so a mismatch (or a stale link) surfaces as an
  // ordinary 404 from the boundary's own overview fetch -- never a
  // synchronous rejection before that fetch runs.
  for (const ref of arbitraryRefs) {
    it(`passes ref ${ref} straight through to the outer shell without blocking on the overview`, async () => {
      const overviewSpy = spyOn(tournamentService, "getPublicOverview").mockResolvedValue(
        overviewFixture
      );

      const result = await TournamentLayout({ children: null, params: paramsFor(ref) });

      expect(result.type).toBe(Fragment);
      expect(overviewSpy).not.toHaveBeenCalled();
    });
  }

  it("resolves metadata from whatever ref the overview accepts, falling back only on failure", async () => {
    spyOn(tournamentService, "getPublicOverview").mockResolvedValue(overviewFixture);

    const metadata = await generateMetadata({ params: paramsFor("summer-clash") });

    expect(metadata.title).toBe("tournamentDetail.metaTitle | Test OWT");
  });

  it("falls back to generic metadata when the overview ref does not resolve", async () => {
    const overviewSpy = spyOn(tournamentService, "getPublicOverview").mockRejectedValue(
      new ApiError(404, [{ msg: "Tournament not found", code: "not_found" }])
    );

    const metadata = await generateMetadata({ params: paramsFor("missing-tournament") });

    expect(overviewSpy).toHaveBeenCalledTimes(1);
    expect(metadata.title).toBe("tournamentDetail.metaTitleFallback | Test OWT");
  });
});
