import { beforeEach, describe, expect, it, vi } from "vitest";

// What the two lobby reads address. They are NOT the same endpoint and must not
// collapse into one: the public path answers a lobby with the hidden columns
// (deaths, penalties) and their values stripped out by `public_view`, and the
// organizer's path answers the same lobby whole. A frontend that reads the
// public path on the entry screen silently loses every hidden column the
// organizer is supposed to be typing into.
const paths: string[] = [];

vi.mock("@/lib/api/fetch", () => ({
  apiFetch: (path: string) => {
    paths.push(path);
    return Promise.resolve({ json: async () => [] });
  }
}));

const { default: ffaService } = await import("@/services/ffa.service");

describe("ffa stage reads", () => {
  beforeEach(() => {
    paths.length = 0;
  });

  it("reads the organizer's stage lobbies from the admin route", async () => {
    await ffaService.getStageAdmin(84, 10);

    expect(paths).toEqual(["/api/v1/admin/tournaments/84/stages/10/ffa"]);
  });

  it("keeps the spectator's stage read on the public route", async () => {
    await ffaService.getStage(84, 10);

    expect(paths).toEqual(["/api/v1/tournaments/84/stages/10/ffa"]);
  });
});
