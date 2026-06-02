import { beforeEach, describe, expect, it, mock } from "bun:test";

// Capture (service, path) passed to apiFetch so we can assert that
// division-grid endpoints are routed to the service that actually serves
// them. /division-grids/** lives only in tournament-service (clientBase
// /api/v1); routing through "app" prepends /api/v1/core and 404s.
const calls: Array<{ service: string; path: string }> = [];

mock.module("@/lib/api-fetch", () => ({
  apiFetch: (service: string, path: string) => {
    calls.push({ service, path });
    return Promise.resolve({ json: async () => [] });
  },
}));

const { default: workspaceService } = await import("@/services/workspace.service");

describe("workspaceService division-grid routing", () => {
  beforeEach(() => {
    calls.length = 0;
  });

  it("routes marketplace workspaces through tournament-service, not app/core", async () => {
    await workspaceService.getDivisionGridMarketplaceWorkspaces(6);

    expect(calls[0]).toEqual({
      service: "tournament",
      path: "division-grids/by-workspace/6/marketplace/workspaces",
    });
  });

  it("routes the mapping GET through tournament-service (matching its PUT sibling)", async () => {
    await workspaceService.getDivisionGridMapping(10, 20);

    expect(calls[0]).toEqual({
      service: "tournament",
      path: "division-grids/mappings/10/20",
    });
  });
});
