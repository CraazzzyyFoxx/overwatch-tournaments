import { afterEach, describe, expect, it, spyOn } from "bun:test";
import { isValidElement } from "react";

import { ApiError } from "@/lib/api-error";
import tournamentService from "@/services/tournament.service";
import type { Tournament } from "@/types/tournament.types";

import TournamentLayout from "./layout";
import TournamentShellError from "./TournamentShellError";

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

afterEach(() => {
  // Restores every service spy even if an assertion fails midway through a case.
  (tournamentService.getPublicOverview as { mockRestore?: () => void }).mockRestore?.();
});

describe("TournamentLayout overview classification", () => {
  it("awaits one overview request before returning the successful shell", async () => {
    const overviewSpy = spyOn(tournamentService, "getPublicOverview").mockResolvedValue({
      ...overviewFixture,
      id: 7201
    });

    const result = await TournamentLayout({ children: null, params: paramsFor("7201") });

    expect(isValidElement(result)).toBe(true);
    expect(overviewSpy).toHaveBeenCalledTimes(1);
    expect(overviewSpy).toHaveBeenCalledWith(7201);
  });

  it("turns an API not-found into Next's notFound control flow before returning JSX", async () => {
    const overviewSpy = spyOn(tournamentService, "getPublicOverview").mockRejectedValue(
      new ApiError(404, [{ msg: "Tournament not found", code: "not_found" }])
    );

    let thrown: unknown;
    try {
      await TournamentLayout({ children: null, params: paramsFor("7202") });
    } catch (error) {
      thrown = error;
    }

    expect(overviewSpy).toHaveBeenCalledTimes(1);
    expect(thrown).toMatchObject({ digest: "NEXT_HTTP_ERROR_FALLBACK;404" });
  });

  it("renders the serializable retry UI for a non-404 overview failure", async () => {
    const overviewSpy = spyOn(tournamentService, "getPublicOverview").mockRejectedValue(
      new Error("upstream unavailable")
    );

    const result = await TournamentLayout({ children: null, params: paramsFor("7203") });

    expect(overviewSpy).toHaveBeenCalledTimes(1);
    expect(isValidElement(result)).toBe(true);
    if (!isValidElement(result)) throw new Error("Expected a React element");
    expect(result.type).toBe(TournamentShellError);
    expect(result.props).toEqual({});
  });

  for (const invalidId of ["not-a-number", "0", "-3", "2.5"]) {
    it(`rejects invalid id ${invalidId} as not-found without an API request`, async () => {
      const overviewSpy = spyOn(tournamentService, "getPublicOverview").mockResolvedValue(
        overviewFixture
      );

      let thrown: unknown;
      try {
        await TournamentLayout({ children: null, params: paramsFor(invalidId) });
      } catch (error) {
        thrown = error;
      }

      expect(overviewSpy).not.toHaveBeenCalled();
      expect(thrown).toMatchObject({ digest: "NEXT_HTTP_ERROR_FALLBACK;404" });
    });
  }
});
