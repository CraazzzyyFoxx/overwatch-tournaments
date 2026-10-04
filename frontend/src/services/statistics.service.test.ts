import { beforeEach, describe, expect, it, vi } from "vitest";

// Capture what each statistics read hands to apiFetch. The homepage and
// /statistics render these on every request; without a Data Cache TTL an
// nginx cache miss turns into six gateway round-trips per render.
const calls: Array<{ path: string; options: Record<string, unknown> }> = [];

vi.mock("@/lib/api/fetch", () => ({
  apiFetch: (path: string, options: Record<string, unknown> = {}) => {
    calls.push({ path, options });
    return Promise.resolve({ json: async () => ({ results: [] }) });
  },
}));

const { default: statisticsService } = await import("@/services/statistics.service");

describe("statisticsService Data Cache", () => {
  beforeEach(() => {
    calls.length = 0;
  });

  it.each([
    ["getTournaments", () => statisticsService.getTournaments()],
    ["getTournamentsDivision", () => statisticsService.getTournamentsDivision()],
    ["getOverallStatistics", () => statisticsService.getOverallStatistics()],
    ["getChampions", () => statisticsService.getChampions()],
    ["getTopWinratePlayers", () => statisticsService.getTopWinratePlayers()],
    ["getTopWonMapsPlayers", () => statisticsService.getTopWonMapsPlayers()],
  ])("%s caches the server-side read for 60 s", async (_name, read) => {
    await read();

    expect(calls[0].options.next).toEqual({ revalidate: 60 });
  });

  it("keeps the workspace in the URL, so tenants never share an entry", async () => {
    await statisticsService.getChampions({ workspaceId: 7 });

    expect(calls[0].options.query).toEqual({ workspace_id: 7, sort: "value", order: "desc" });
    expect(calls[0].options.next).toEqual({ revalidate: 60 });
  });
});
