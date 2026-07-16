import { beforeEach, describe, expect, it, mock } from "bun:test";

type Call = {
  path: string;
  options?: {
    skipWorkspace?: boolean;
    query?: Record<string, unknown>;
  };
};

const calls: Call[] = [];

mock.module("@/lib/api-fetch", () => ({
  apiFetch: (path: string, options?: Call["options"]) => {
    calls.push({ path, options });
    return Promise.resolve({ json: async () => ({ results: [], total: 0 }) });
  },
}));

mock.module("@/lib/normalize-paginated-response", () => ({
  normalizePaginatedResponse: (response: unknown) => response,
}));

const { default: teamService } = await import("@/services/team.service");

describe("teamService.getAll", () => {
  beforeEach(() => {
    calls.length = 0;
  });

  it("scopes teams to both the tournament and its explicit workspace", async () => {
    await teamService.getAll({
      tournamentId: 72,
      workspaceId: 6,
      sort: "name",
      order: "desc",
    });

    expect(calls).toEqual([
      {
        path: "/api/v1/teams",
        options: {
          skipWorkspace: true,
          query: {
            page: 1,
            per_page: -1,
            sort: "name",
            order: "desc",
            entities: ["players", "players.user", "placement", "group", "tournament"],
            tournament_id: 72,
            workspace_id: 6,
          },
        },
      },
    ]);
  });
});
