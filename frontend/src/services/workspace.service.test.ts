import { beforeEach, describe, expect, it, mock } from "bun:test";

// Capture the path passed to apiFetch. Division-grid endpoints live under the
// unified /api/v1 namespace (tournament-worker); this guards that the service
// builds the correct gateway path.
const calls: Array<{ path: string }> = [];

mock.module("@/lib/api-fetch", () => ({
  apiFetch: (path: string) => {
    calls.push({ path });
    return Promise.resolve({ json: async () => [] });
  },
}));

const { default: workspaceService } = await import("@/services/workspace.service");

describe("workspaceService division-grid routing", () => {
  beforeEach(() => {
    calls.length = 0;
  });

  it("builds the marketplace-workspaces path under /api/v1", async () => {
    await workspaceService.getDivisionGridMarketplaceWorkspaces(6);

    expect(calls[0].path).toBe(
      "/api/v1/division-grids/by-workspace/6/marketplace/workspaces",
    );
  });

  it("builds the mapping GET path under /api/v1 (matching its PUT sibling)", async () => {
    await workspaceService.getDivisionGridMapping(10, 20);

    expect(calls[0].path).toBe("/api/v1/division-grids/mappings/10/20");
  });
});
