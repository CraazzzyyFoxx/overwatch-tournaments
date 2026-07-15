import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it, spyOn } from "bun:test";

import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import tournamentService from "@/services/tournament.service";
import type { Tournament } from "@/types/tournament.types";

import { tournamentOverviewQueryOptions } from "../_queries/tournamentOverview";

describe("tournament overview query contract", () => {
  it("is defined in a server-safe module", () => {
    const source = readFileSync(
      join(import.meta.dir, "..", "_queries", "tournamentOverview.ts"),
      "utf8",
    );

    expect(source).not.toMatch(/["']use client["']/);
  });

  it("keeps workspace-aware collection variants below their realtime prefixes", () => {
    expect(tournamentQueryKeys.teams(72, 6)).toEqual(["teams", 72, 6]);
    expect(tournamentQueryKeys.bracketStandings(72, 6)).toEqual([
      "standings",
      72,
      "bracket",
      6,
    ]);
  });

  it("uses the detail key and public overview fetcher with a one-minute stale time", async () => {
    const overview = { id: 72 } as Tournament;
    const overviewSpy = spyOn(tournamentService, "getPublicOverview").mockResolvedValue(overview);
    const options = tournamentOverviewQueryOptions(72);

    expect(options.queryKey).toEqual(tournamentQueryKeys.detail(72));
    expect(options.staleTime).toBe(60_000);

    const queryFn = options.queryFn;
    if (typeof queryFn !== "function") {
      throw new Error("Expected tournament overview queryFn to be callable");
    }

    await expect(queryFn({} as never)).resolves.toBe(overview);
    expect(overviewSpy).toHaveBeenCalledWith(72);

    overviewSpy.mockRestore();
  });
});
