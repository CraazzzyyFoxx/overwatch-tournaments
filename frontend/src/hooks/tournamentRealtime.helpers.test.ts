import { describe, expect, it } from "bun:test";

import {
  getTournamentRealtimeUpdatePlan,
  parseTournamentRealtimeMessage,
} from "@/hooks/tournamentRealtime.helpers";
import { buildRealtimeWebSocketUrl } from "@/services/realtime.service";

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
      42
    );

    expect(message).toEqual({
      tournamentId: 42,
      reason: "results_changed",
    });
  });

  it("builds a results-scoped plan that skips structure queries and the route refresh", () => {
    const plan = getTournamentRealtimeUpdatePlan(42, 7, "results_changed");

    expect(plan.workspaceScope).toBe("results");
    expect(plan.shouldRefreshRoute).toBe(false);
    // Result-derived queries are invalidated.
    expect(plan.queryKeys).toContainEqual(["tournament", 42]);
    expect(plan.queryKeys).toContainEqual(["tournament", 42, "stages"]);
    expect(plan.queryKeys).toContainEqual(["hero-playtime", "tournament", 42]);
    expect(plan.queryKeys).toContainEqual(["standings", 42]);
    expect(plan.queryKeys).toContainEqual(["standings-table", 42]);
    expect(plan.queryKeys).toContainEqual(["encounters", "tournament", 42]);
    expect(plan.queryKeys).toContainEqual(["standings", 42, 7]);
    expect(plan.queryKeys).toContainEqual(["encounters", "tournament", 42, 7]);
    // Structure-only queries are NOT touched by a score recalculation.
    expect(plan.queryKeys).not.toContainEqual(["teams", 42]);
    expect(plan.queryKeys).not.toContainEqual(["registration", 7, 42]);
    expect(plan.queryKeys).not.toContainEqual(["registrations-list", 7, 42]);
    expect(plan.queryKeys).not.toContainEqual(["registration-form", 7, 42]);
  });

  it("builds a full-scope plan for structure updates and requires a route refresh", () => {
    const plan = getTournamentRealtimeUpdatePlan(42, 7, "structure_changed");

    expect(plan.workspaceScope).toBe("full");
    expect(plan.shouldRefreshRoute).toBe(true);
    expect(plan.queryKeys).toContainEqual(["teams", 42]);
    expect(plan.queryKeys).toContainEqual(["registration", 7, 42]);
    expect(plan.queryKeys).toContainEqual(["registrations-list", 7, 42]);
    expect(plan.queryKeys).toContainEqual(["registration-form", 7, 42]);
  });

  it("builds websocket URLs from relative realtime API bases", () => {
    expect(
      buildRealtimeWebSocketUrl("/api/realtime", "https://example.test")
    ).toBe("wss://example.test/api/realtime/ws");
  });
});
