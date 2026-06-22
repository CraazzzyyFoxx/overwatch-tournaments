import { afterEach, beforeEach, describe, expect, it, mock } from "bun:test";

import { useAuthProfileStore } from "@/stores/auth-profile.store";

// Drives the REAL fetchMe / refreshAccessToken via a URL-aware fetch mock (no
// module mock that could leak across files). getTokenFromCookies resolves to
// undefined here (window is stubbed but there's no document for js-cookie).

type Globals = { window?: unknown; fetch?: typeof fetch };
const g = globalThis as unknown as Globals;

const originalFetch = globalThis.fetch;

// Status the mocked POST /auth/refresh returns: 200 => refreshed, 401 => dead
// session, anything else => transient error. /api/auth/me always returns 401.
let refreshStatus = 500;

beforeEach(() => {
  refreshStatus = 500;
  g.window = {};
  g.fetch = mock(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/auth/refresh")) {
      return new Response(refreshStatus === 200 ? JSON.stringify({ access_token: "T2" }) : null, {
        status: refreshStatus,
      });
    }
    return new Response(null, { status: 401 });
  }) as unknown as typeof fetch;

  useAuthProfileStore.setState({
    status: "idle",
    user: undefined,
    error: undefined,
    lastFetchedAt: undefined,
  });
});

afterEach(() => {
  g.fetch = originalFetch;
  delete g.window;
});

describe("auth-profile store fetchMe", () => {
  it("does not get stuck in 'loading' on initial load when the refresh transiently errors", async () => {
    refreshStatus = 500;
    await useAuthProfileStore.getState().fetchMe();
    expect(useAuthProfileStore.getState().status).toBe("error");
  });

  it("preserves an existing authenticated state on a transient refresh error", async () => {
    useAuthProfileStore.setState({
      status: "authenticated",
      user: {
        username: "x",
        roles: [],
        permissions: [],
        isSuperuser: false,
        workspaces: [],
        linkedPlayers: [],
      },
      lastFetchedAt: Date.now() - 5 * 60_000,
    });
    refreshStatus = 500;

    await useAuthProfileStore.getState().fetchMe({ staleMs: 60_000 });

    expect(useAuthProfileStore.getState().status).toBe("authenticated");
  });

  it("goes anonymous when the session is genuinely dead (refresh returns 401)", async () => {
    refreshStatus = 401;
    await useAuthProfileStore.getState().fetchMe();
    expect(useAuthProfileStore.getState().status).toBe("anonymous");
  });
});
