import { beforeEach, describe, expect, it, mock } from "bun:test";

// Capture the options apiFetch is called with, so we can assert how
// getActive threads skipWorkspace through.
type Call = { path: string; options: { skipWorkspace?: boolean } | undefined };
const calls: Call[] = [];

mock.module("@/lib/api-fetch", () => ({
  apiFetch: (path: string, options?: { skipWorkspace?: boolean }) => {
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
