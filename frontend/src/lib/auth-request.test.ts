import { afterEach, beforeEach, describe, expect, it, mock } from "bun:test";

import { retryWithRefreshOnUnauthorized } from "@/lib/auth-request";

// We exercise the REAL refreshAccessToken / notifyUnauthorized and drive their
// behaviour from the edges (a URL-aware fetch mock + a stubbed window), so this
// file doesn't register any module mock that could leak into other test files.

type Globals = { window?: unknown; CustomEvent?: unknown; fetch?: typeof fetch };
const g = globalThis as unknown as Globals;

const originalFetch = globalThis.fetch;
const dispatchEvent = mock((_event: unknown) => true);

// Status the mocked POST /auth/refresh returns: 200 => refreshed, 401 => dead
// session, anything else => transient error.
let refreshStatus = 500;

const unauthorized = () => new Response(null, { status: 401 });
const ok = () => new Response(null, { status: 200 });

beforeEach(() => {
  refreshStatus = 500;
  dispatchEvent.mockClear();
  g.window = { dispatchEvent };
  g.CustomEvent = class {
    type: string;
    constructor(type: string) {
      this.type = type;
    }
  };
  g.fetch = mock(async () =>
    new Response(refreshStatus === 200 ? JSON.stringify({ access_token: "T2" }) : null, {
      status: refreshStatus,
    }),
  ) as unknown as typeof fetch;
});

afterEach(() => {
  g.fetch = originalFetch;
  delete g.window;
  delete g.CustomEvent;
});

describe("retryWithRefreshOnUnauthorized", () => {
  it("passes through non-401 responses without refreshing", async () => {
    const res = await retryWithRefreshOnUnauthorized({
      response: ok(),
      runRequest: async () => ok(),
    });
    expect(res.status).toBe(200);
    expect(dispatchEvent).not.toHaveBeenCalled();
  });

  it("does not refresh when an explicit token was supplied", async () => {
    const res = await retryWithRefreshOnUnauthorized({
      response: unauthorized(),
      token: "explicit",
      runRequest: async () => ok(),
    });
    expect(res.status).toBe(401);
    expect(dispatchEvent).not.toHaveBeenCalled();
  });

  it("logs out only when the session is genuinely dead (refresh returns 401)", async () => {
    refreshStatus = 401;
    const res = await retryWithRefreshOnUnauthorized({
      response: unauthorized(),
      runRequest: async () => ok(),
    });
    expect(dispatchEvent).toHaveBeenCalledTimes(1);
    expect(res.status).toBe(401);
  });

  it("does NOT log out on a transient refresh error", async () => {
    refreshStatus = 500;
    const res = await retryWithRefreshOnUnauthorized({
      response: unauthorized(),
      runRequest: async () => ok(),
    });
    expect(dispatchEvent).not.toHaveBeenCalled();
    expect(res.status).toBe(401);
  });

  it("retries once with the new token after a successful refresh", async () => {
    refreshStatus = 200;
    const runRequest = mock(async (_token?: string) => ok());
    const res = await retryWithRefreshOnUnauthorized({
      response: unauthorized(),
      runRequest,
    });
    expect(runRequest).toHaveBeenCalledTimes(1);
    expect(runRequest).toHaveBeenCalledWith("T2");
    expect(res.status).toBe(200);
    expect(dispatchEvent).not.toHaveBeenCalled();
  });

  it("does NOT log out when the post-refresh retry still 401s (per-resource, not session death)", async () => {
    refreshStatus = 200;
    const res = await retryWithRefreshOnUnauthorized({
      response: unauthorized(),
      runRequest: async () => unauthorized(),
    });
    expect(res.status).toBe(401);
    expect(dispatchEvent).not.toHaveBeenCalled();
  });
});
