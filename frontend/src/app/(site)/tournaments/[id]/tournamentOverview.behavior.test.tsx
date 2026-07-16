import { afterEach, describe, expect, it, mock, spyOn } from "bun:test";
import { HydrationBoundary } from "@tanstack/react-query";
import { isValidElement, Suspense, type ReactElement } from "react";

import { ApiError } from "@/lib/api-error";
import tournamentService from "@/services/tournament.service";
import type { Tournament } from "@/types/tournament.types";

import TournamentOverviewBoundary from "./TournamentOverviewBoundary";
import TournamentShellError from "./TournamentShellError";
import { TournamentShellSkeleton } from "./_components/TournamentSkeletons";

mock.module("next-intl/server", () => ({
  getTranslations: async () => (key: string) => key
}));
mock.module("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => (key: string) => key
}));
mock.module("@/lib/site-metadata", () => ({
  resolveSiteMetadata: async () => ({ name: "Test OWT", origin: "https://example.test" })
}));

const { default: TournamentLayout, generateMetadata } = await import("./layout");
const { default: TournamentIndexPage } = await import("./page");

const overviewFixture: Tournament = {
  id: 72,
  created_at: new Date("2026-01-01T00:00:00Z"),
  updated_at: null,
  workspace_id: 4,
  name: "Summer Clash",
  start_date: new Date("2026-07-15T12:00:00Z"),
  end_date: new Date("2026-07-16T12:00:00Z"),
  number: 72,
  description: "Public tournament",
  challonge_id: null,
  challonge_slug: null,
  is_league: false,
  is_finished: false,
  is_hidden: false,
  team_formation: "balancer",
  status: "live",
  registration_opens_at: null,
  registration_closes_at: null,
  check_in_opens_at: null,
  check_in_closes_at: null,
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

const paramsFor = (id: string) => Promise.resolve({ id });
const afterTurn = () => new Promise<void>((resolve) => setTimeout(resolve, 20));
const invalidRawIds = [
  "not-a-number",
  "0",
  "-3",
  "2.5",
  "1e2",
  "0x48",
  "+72",
  "072",
  " 72",
  "72 ",
  "9007199254740992"
];

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

async function captureThrown(operation: () => Promise<unknown>) {
  try {
    await operation();
    return undefined;
  } catch (error) {
    return error;
  }
}

afterEach(() => {
  (tournamentService.getPublicOverview as { mockRestore?: () => void }).mockRestore?.();
});

describe("TournamentLayout streaming overview", () => {
  it("exposes the exact shell fallback while a valid tournament overview is unresolved", async () => {
    const pendingOverview = deferred<Tournament>();
    const overviewSpy = spyOn(tournamentService, "getPublicOverview").mockReturnValue(
      pendingOverview.promise
    );
    const layoutPromise = TournamentLayout({ children: null, params: paramsFor("7301") });

    const firstResult = await Promise.race([
      layoutPromise.then((result) => ({ kind: "layout" as const, result })),
      afterTurn().then(() => ({ kind: "waiting" as const }))
    ]);

    if (firstResult.kind === "waiting") {
      pendingOverview.resolve({ ...overviewFixture, id: 7301 });
      await layoutPromise;
    }

    expect(firstResult.kind).toBe("layout");
    if (firstResult.kind !== "layout") return;
    expect(firstResult.result.type).toBe(Suspense);
    const suspenseProps = firstResult.result.props as {
      fallback: ReactElement;
      children: ReactElement;
    };
    expect(suspenseProps.fallback.type).toBe(TournamentShellSkeleton);
    expect(overviewSpy).not.toHaveBeenCalled();

    const boundaryPromise = TournamentOverviewBoundary(
      suspenseProps.children.props as Parameters<typeof TournamentOverviewBoundary>[0]
    );
    const boundaryBeforeOverview = await Promise.race([
      boundaryPromise.then(() => "resolved" as const),
      afterTurn().then(() => "waiting" as const)
    ]);

    expect(overviewSpy).toHaveBeenCalledTimes(1);
    expect(boundaryBeforeOverview).toBe("waiting");

    pendingOverview.resolve({ ...overviewFixture, id: 7301 });
    const hydrated = await boundaryPromise;
    expect(isValidElement(hydrated)).toBe(true);
    if (!isValidElement(hydrated)) throw new Error("Expected hydrated overview element");
    expect(hydrated.type).toBe(HydrationBoundary);
  });

  it("uses intentional streamed notFound control flow for an API 404", async () => {
    const overviewSpy = spyOn(tournamentService, "getPublicOverview").mockRejectedValue(
      new ApiError(404, [{ msg: "Tournament not found", code: "not_found" }])
    );

    const thrown = await captureThrown(() =>
      Promise.resolve(TournamentOverviewBoundary({ tournamentId: 7302, children: null }))
    );

    expect(overviewSpy).toHaveBeenCalledTimes(1);
    expect(thrown).toMatchObject({ digest: "NEXT_HTTP_ERROR_FALLBACK;404" });
  });

  it("renders the serializable retry UI for a non-404 overview failure", async () => {
    const overviewSpy = spyOn(tournamentService, "getPublicOverview").mockRejectedValue(
      new Error("upstream unavailable")
    );

    const result = await TournamentOverviewBoundary({ tournamentId: 7303, children: null });

    expect(overviewSpy).toHaveBeenCalledTimes(1);
    expect(isValidElement(result)).toBe(true);
    if (!isValidElement(result)) throw new Error("Expected a React element");
    expect(result.type).toBe(TournamentShellError);
    expect(result.props).toEqual({});
  });

  it("hydrates a successful overview after the boundary resolves", async () => {
    const overviewSpy = spyOn(tournamentService, "getPublicOverview").mockResolvedValue({
      ...overviewFixture,
      id: 7304
    });

    const result = await TournamentOverviewBoundary({ tournamentId: 7304, children: null });

    expect(overviewSpy).toHaveBeenCalledTimes(1);
    expect(isValidElement(result)).toBe(true);
    if (!isValidElement(result)) throw new Error("Expected a React element");
    expect(result.type).toBe(HydrationBoundary);
  });

  it("accepts canonical decimal id 72 without blocking the outer shell", async () => {
    const overviewSpy = spyOn(tournamentService, "getPublicOverview").mockResolvedValue(
      overviewFixture
    );

    const result = await TournamentLayout({ children: null, params: paramsFor("72") });

    expect(result.type).toBe(Suspense);
    expect(overviewSpy).not.toHaveBeenCalled();
  });

  for (const invalidId of invalidRawIds) {
    it(`rejects invalid id ${invalidId} before streaming without an API request`, async () => {
      const overviewSpy = spyOn(tournamentService, "getPublicOverview").mockResolvedValue(
        overviewFixture
      );

      const thrown = await captureThrown(() =>
        TournamentLayout({ children: null, params: paramsFor(invalidId) })
      );

      expect(overviewSpy).not.toHaveBeenCalled();
      expect(thrown).toMatchObject({ digest: "NEXT_HTTP_ERROR_FALLBACK;404" });
    });
  }

  it("returns fallback metadata for non-canonical ids without an overview request", async () => {
    const overviewSpy = spyOn(tournamentService, "getPublicOverview").mockResolvedValue(
      overviewFixture
    );

    for (const invalidId of invalidRawIds) {
      const metadata = await generateMetadata({ params: paramsFor(invalidId) });
      expect(metadata.title).toBe("tournamentDetail.metaTitleFallback | Test OWT");
    }

    expect(overviewSpy).not.toHaveBeenCalled();
  });

  it("rejects a non-canonical index-route alias before loading or redirecting", async () => {
    const overviewSpy = spyOn(tournamentService, "getPublicOverview").mockResolvedValue(
      overviewFixture
    );

    const thrown = await captureThrown(() =>
      TournamentIndexPage({ params: paramsFor("0x48"), searchParams: Promise.resolve({}) })
    );

    expect(overviewSpy).not.toHaveBeenCalled();
    expect(thrown).toMatchObject({ digest: "NEXT_HTTP_ERROR_FALLBACK;404" });
  });
});
