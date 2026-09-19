import { afterEach, beforeEach, describe, expect, it, mock } from "bun:test";

import { resetRefreshStateForTests } from "@/lib/auth-tokens";
import { useAuthProfileStore } from "@/stores/auth-profile.store";

// Drives the REAL fetchMe / refreshAccessToken via a URL-aware fetch mock (no
// module mock that could leak across files). getTokenFromCookies resolves to
// undefined here (window is stubbed but there's no document for js-cookie), so
// the FIRST /api/v1/auth/me call never carries an Authorization header — which is
// exactly the production case this store has to survive.

type Globals = { window?: unknown; fetch?: typeof fetch };
const g = globalThis as unknown as Globals;

const originalFetch = globalThis.fetch;

// Status the mocked POST /auth/refresh returns: 200 => refreshed, 401 => dead
// session, anything else => transient error.
let refreshStatus = 500;
// Status /api/v1/auth/me returns for the unauthenticated (no-bearer) attempt.
let meStatus = 401;

const profile = {
  id: 7,
  username: "x",
  roles: [],
  permissions: [],
  is_superuser: false,
  linked_players: [],
  workspaces: [],
};

const authenticatedState = {
  status: "authenticated" as const,
  user: {
    username: "x",
    roles: [],
    permissions: [],
    denies: [],
    isSuperuser: false,
    workspaces: [],
    linkedPlayers: [],
  },
  lastFetchedAt: Date.now() - 5 * 60_000,
};

// Every URL the store requested, in order — cheaper and safer to assert against
// than reaching into the mock's internals.
let requested: string[] = [];

// `globalThis.window` is a non-writable accessor under current Bun, so a plain
// `g.window = {}` throws "Attempted to assign to readonly property" before a
// single assertion runs. Redefining the property does what the assignment meant.
// (This file only started failing once CI actually ran the bun:test half.)
function stubWindow(value: unknown): void {
  Object.defineProperty(globalThis, "window", {
    value,
    writable: true,
    configurable: true,
  });
}

beforeEach(() => {
  refreshStatus = 500;
  meStatus = 401;
  requested = [];
  resetRefreshStateForTests();
  stubWindow({});
  g.fetch = mock(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    requested.push(url);
    if (url.includes("/auth/refresh")) {
      return new Response(refreshStatus === 200 ? JSON.stringify({ access_token: "T2" }) : null, {
        status: refreshStatus,
      });
    }
    // A bearer only exists on the post-refresh retry (see the note above), so it
    // stands in for "the refresh handed us a usable token".
    if (new Headers(init?.headers).has("Authorization")) {
      return new Response(JSON.stringify(profile), { status: 200 });
    }
    return new Response(null, { status: meStatus });
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
  stubWindow(undefined);
});

describe("auth-profile store fetchMe", () => {
  it("does not get stuck in 'loading' on initial load when the refresh transiently errors", async () => {
    refreshStatus = 500;
    await useAuthProfileStore.getState().fetchMe();
    expect(useAuthProfileStore.getState().status).toBe("error");
  });

  it("preserves an existing authenticated state on a transient refresh error", async () => {
    useAuthProfileStore.setState(authenticatedState);
    refreshStatus = 500;

    await useAuthProfileStore.getState().fetchMe({ staleMs: 60_000 });

    expect(useAuthProfileStore.getState().status).toBe("authenticated");
  });

  it("goes anonymous when the session is genuinely dead (refresh returns 401)", async () => {
    refreshStatus = 401;
    await useAuthProfileStore.getState().fetchMe();
    expect(useAuthProfileStore.getState().status).toBe("anonymous");
  });

  // The production regression: the gateway answered 403 ("Not authenticated")
  // for a request with no bearer, so an access cookie that had merely expired
  // never triggered a refresh and a live 30-day session rendered as logged out.
  it("refreshes and authenticates when /me answers 403 for a missing bearer", async () => {
    meStatus = 403;
    refreshStatus = 200;

    await useAuthProfileStore.getState().fetchMe();

    expect(useAuthProfileStore.getState().status).toBe("authenticated");
    expect(useAuthProfileStore.getState().user?.username).toBe("x");
  });

  it("goes anonymous on 403 when the refresh also says the session is dead", async () => {
    meStatus = 403;
    refreshStatus = 401;

    await useAuthProfileStore.getState().fetchMe();

    expect(useAuthProfileStore.getState().status).toBe("anonymous");
  });

  it("keeps the known identity when /me is unavailable (5xx says nothing about who the user is)", async () => {
    useAuthProfileStore.setState(authenticatedState);
    meStatus = 503;

    await useAuthProfileStore.getState().fetchMe({ staleMs: 60_000 });

    expect(useAuthProfileStore.getState().status).toBe("authenticated");
    expect(useAuthProfileStore.getState().user?.username).toBe("x");
  });

  it("surfaces an error instead of an identity when /me is unavailable on first load", async () => {
    meStatus = 503;

    await useAuthProfileStore.getState().fetchMe();

    expect(useAuthProfileStore.getState().status).toBe("error");
  });
});

describe("refresh latch", () => {
  it("stops re-POSTing /auth/refresh once the session is known dead", async () => {
    meStatus = 401;
    refreshStatus = 401;

    await useAuthProfileStore.getState().fetchMe();
    await useAuthProfileStore.getState().fetchMe({ force: true });

    const refreshCalls = requested.filter((url) => url.includes("/auth/refresh"));
    expect(refreshCalls.length).toBe(1);
  });
});
