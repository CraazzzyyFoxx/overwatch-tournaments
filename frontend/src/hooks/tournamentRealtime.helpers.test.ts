import { describe, expect, it } from "bun:test";
import { QueryClient } from "@tanstack/react-query";

import {
  applyTournamentRealtimeCatchUp,
  applyTournamentRealtimeUpdate,
  createTrailingCoalescer,
  getTournamentRealtimeCatchUpPlan,
  getTournamentRealtimeUpdatePlan,
  parseTournamentRealtimeMessage,
} from "@/hooks/tournamentRealtime.helpers";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { buildRealtimeWebSocketUrl } from "@/services/realtime.service";

function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
}

function expectInvalidated(
  queryClient: QueryClient,
  queryKey: readonly unknown[],
  expected: boolean,
): void {
  expect(queryClient.getQueryState(queryKey)?.isInvalidated).toBe(expected);
}

describe("tournament realtime helpers", () => {
  it("parses tournament update websocket messages for the active tournament", () => {
    const message = parseTournamentRealtimeMessage(
      JSON.stringify({
        type: "tournament:updated",
        data: {
          tournament_id: 42,
          reason: "results_changed",
        },
      }),
      42,
    );

    expect(message).toEqual({
      tournamentId: 42,
      reason: "results_changed",
    });
  });

  it("maps bracket changes to the encounter prefix only", () => {
    expect(getTournamentRealtimeUpdatePlan(42, 7, "bracket_changed")).toEqual({
      workspaceScope: "bracket",
      queryKeys: [tournamentQueryKeys.encounters(42)],
      shouldRefreshRoute: false,
    });
  });

  it("maps result changes to overview, stages, heroes, all standings, and encounters", () => {
    expect(getTournamentRealtimeUpdatePlan(42, 7, "results_changed")).toEqual({
      workspaceScope: "results",
      queryKeys: [
        tournamentQueryKeys.detail(42),
        tournamentQueryKeys.stages(42),
        tournamentQueryKeys.heroPlaytime(42),
        tournamentQueryKeys.standings(42),
        tournamentQueryKeys.bracketStandings(42),
        tournamentQueryKeys.encounters(42),
      ],
      shouldRefreshRoute: false,
    });
  });

  it("adds team and participant prefixes for structure changes", () => {
    expect(getTournamentRealtimeUpdatePlan(42, 7, "structure_changed")).toEqual({
      workspaceScope: "full",
      queryKeys: [
        tournamentQueryKeys.detail(42),
        tournamentQueryKeys.stages(42),
        tournamentQueryKeys.heroPlaytime(42),
        tournamentQueryKeys.standings(42),
        tournamentQueryKeys.bracketStandings(42),
        tournamentQueryKeys.encounters(42),
        tournamentQueryKeys.teams(42),
        tournamentQueryKeys.registration(7, 42),
        tournamentQueryKeys.registrationsList(7, 42),
        tournamentQueryKeys.registrationForm(7, 42),
      ],
      shouldRefreshRoute: true,
    });
  });

  it("omits workspace-bound participant prefixes until the workspace is known", () => {
    const plan = getTournamentRealtimeUpdatePlan(42, null, "structure_changed");

    expect(plan.queryKeys).toEqual([
      tournamentQueryKeys.detail(42),
      tournamentQueryKeys.stages(42),
      tournamentQueryKeys.heroPlaytime(42),
      tournamentQueryKeys.standings(42),
      tournamentQueryKeys.bracketStandings(42),
      tournamentQueryKeys.encounters(42),
      tournamentQueryKeys.teams(42),
    ]);
  });

  it("invalidates workspace-aware variants through their public prefixes without broad bracket invalidation", () => {
    const queryClient = createQueryClient();
    const encounterVariant = tournamentQueryKeys.encountersPage(42, 7, 3, "final");
    const standingsVariant = tournamentQueryKeys.bracketStandings(42, 7);
    const teamsVariant = tournamentQueryKeys.teams(42, 7);
    const unrelated = tournamentQueryKeys.detail(99);

    for (const queryKey of [encounterVariant, standingsVariant, teamsVariant, unrelated]) {
      queryClient.setQueryData(queryKey, { value: queryKey });
    }

    applyTournamentRealtimeUpdate(queryClient, 42, 7, "bracket_changed");

    expectInvalidated(queryClient, encounterVariant, true);
    expectInvalidated(queryClient, standingsVariant, false);
    expectInvalidated(queryClient, teamsVariant, false);
    expectInvalidated(queryClient, unrelated, false);
  });

  it("builds a catch-up plan covering every public tournament dataset", () => {
    expect(getTournamentRealtimeCatchUpPlan(42, 7)).toEqual([
      tournamentQueryKeys.detail(42),
      tournamentQueryKeys.stages(42),
      tournamentQueryKeys.teams(42),
      tournamentQueryKeys.heroPlaytime(42),
      tournamentQueryKeys.standings(42),
      tournamentQueryKeys.bracketStandings(42),
      tournamentQueryKeys.encounters(42),
      tournamentQueryKeys.registration(7, 42),
      tournamentQueryKeys.registrationsList(7, 42),
      tournamentQueryKeys.registrationForm(7, 42),
    ]);
  });

  it("catch-up invalidates workspace-aware variants and leaves another tournament intact", () => {
    const queryClient = createQueryClient();
    const tournamentQueries = [
      tournamentQueryKeys.detail(42),
      tournamentQueryKeys.stages(42),
      tournamentQueryKeys.teams(42, 7),
      tournamentQueryKeys.heroPlaytime(42),
      tournamentQueryKeys.standings(42, 7),
      tournamentQueryKeys.bracketStandings(42, 7),
      tournamentQueryKeys.encountersPage(42, 7, 2, "semi"),
      tournamentQueryKeys.registration(7, 42),
      tournamentQueryKeys.registrationsList(7, 42),
      tournamentQueryKeys.registrationForm(7, 42),
    ];
    const unrelated = tournamentQueryKeys.teams(99, 7);

    for (const queryKey of [...tournamentQueries, unrelated]) {
      queryClient.setQueryData(queryKey, { value: queryKey });
    }

    applyTournamentRealtimeCatchUp(queryClient, 42, 7);

    for (const queryKey of tournamentQueries) {
      expectInvalidated(queryClient, queryKey, true);
    }
    expectInvalidated(queryClient, unrelated, false);
  });

  it("trails refresh bursts, starts a later burst, and cancels pending work", () => {
    type PendingTimer = { callback: () => void; delay: number; cancelled: boolean };
    const timers: PendingTimer[] = [];
    const clock = {
      setTimeout(callback: () => void, delay: number): PendingTimer {
        const timer = { callback, delay, cancelled: false };
        timers.push(timer);
        return timer;
      },
      clearTimeout(timer: PendingTimer): void {
        timer.cancelled = true;
      },
    };
    let refreshCount = 0;
    const coalescer = createTrailingCoalescer(() => {
      refreshCount += 1;
    }, 500, clock);

    coalescer.schedule();
    coalescer.schedule();
    coalescer.schedule();

    expect(timers.map((timer) => timer.delay)).toEqual([500, 500, 500]);
    expect(timers.slice(0, 2).every((timer) => timer.cancelled)).toBe(true);
    timers[2].callback();
    expect(refreshCount).toBe(1);

    coalescer.schedule();
    timers[3].callback();
    expect(refreshCount).toBe(2);

    coalescer.schedule();
    coalescer.cancel();
    expect(timers[4].cancelled).toBe(true);
    timers[4].callback();
    expect(refreshCount).toBe(2);
  });

  it("builds websocket URLs from relative realtime API bases", () => {
    expect(
      buildRealtimeWebSocketUrl("/api/realtime", "https://example.test"),
    ).toBe("wss://example.test/api/realtime/ws");
  });
});
