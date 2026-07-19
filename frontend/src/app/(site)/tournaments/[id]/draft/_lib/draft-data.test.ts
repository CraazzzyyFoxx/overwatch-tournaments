import { describe, expect, it } from "vitest";

import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { draftEndpoints } from "@/services/draft.service";

describe("draft data contracts", () => {
  it("uses narrow feasibility and current-pick option query keys", () => {
    expect(tournamentQueryKeys.draftFeasibility(12)).toEqual([
      "draft",
      "session",
      12,
      "feasibility"
    ]);
    expect(tournamentQueryKeys.draftPickOptions(44)).toEqual([
      "draft",
      "pick",
      44,
      "options"
    ]);
  });

  it("builds the new gateway endpoint paths", () => {
    expect(draftEndpoints.feasibility(12)).toBe(
      "/api/balancer/draft/sessions/12/feasibility"
    );
    expect(draftEndpoints.pickOptions(44)).toBe("/api/balancer/draft/picks/44/options");
    expect(draftEndpoints.playerRole(12, 20)).toBe(
      "/api/balancer/draft/sessions/12/players/20/roles"
    );
  });
});
