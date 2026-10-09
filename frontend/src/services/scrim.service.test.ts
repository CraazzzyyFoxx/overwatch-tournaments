import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock("@/lib/api/fetch", () => ({ apiFetch }));
import scrimService from "./scrim.service";

beforeEach(() => {
  apiFetch.mockReset().mockResolvedValue(new Response(JSON.stringify({ workspace_id: 4 })));
});

describe("scrim room reads", () => {
  it("keeps failures visible instead of treating forbidden or failed reads as missing rooms", async () => {
    for (const status of [403, 500]) {
      apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Unavailable" }), { status }));
      await expect(scrimService.getRoom("room-B")).rejects.toBeDefined();
    }
    apiFetch.mockResolvedValueOnce(new Response(null, { status: 404 }));
    await expect(scrimService.getRoom("missing")).resolves.toBeNull();
  });
});
