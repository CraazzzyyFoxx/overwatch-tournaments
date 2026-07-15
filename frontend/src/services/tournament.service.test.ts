import { beforeEach, describe, expect, it, mock } from "bun:test";

// Capture the real service boundary so tests can assert the public API contract
// without coupling to apiFetch's internal URL serialization.
type Call = {
  path: string;
  options:
    | {
        skipWorkspace?: boolean;
        query?: Record<string, unknown>;
      }
    | undefined;
};
const calls: Call[] = [];

mock.module("@/lib/api-fetch", () => ({
  apiFetch: (
    path: string,
    options?: { skipWorkspace?: boolean; query?: Record<string, unknown> },
  ) => {
    calls.push({ path, options });
    return Promise.resolve({ json: async () => ({ results: [], total: 0 }) });
  },
}));

mock.module("@/lib/normalize-paginated-response", () => ({
  normalizePaginatedResponse: (r: unknown) => r,
}));

const { default: tournamentService } = await import("@/services/tournament.service");

describe("tournamentService.getActive", () => {
  beforeEach(() => {
    calls.length = 0;
  });

  it("defaults to skipWorkspace: true (platform-wide) when called with no args", async () => {
    await tournamentService.getActive();
    expect(calls[0].options?.skipWorkspace).toBe(true);
  });

  it("forwards skipWorkspace: false when the caller opts into workspace scope", async () => {
    await tournamentService.getActive({ skipWorkspace: false });
    expect(calls[0].options?.skipWorkspace).toBe(false);
  });
});

describe("tournamentService.getPublicOverview", () => {
  beforeEach(() => {
    calls.length = 0;
  });

  it("loads the fixed public overview without ambient workspace scoping", async () => {
    await tournamentService.getPublicOverview(72);

    expect(calls).toEqual([
      {
        path: "/api/v1/tournaments/72",
        options: {
          skipWorkspace: true,
          query: {
            entities: [
              "stages",
              "participants_count",
              "registrations_count",
              "teams_count",
            ],
          },
        },
      },
    ]);
  });
});
