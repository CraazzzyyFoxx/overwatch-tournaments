import { afterEach, beforeEach, describe, expect, it, mock } from "bun:test";

// /auth/sso (Task 9) is the far side of the custom-domain login-ticket
// handoff: it runs ON the workspace's custom domain and establishes a brand
// new session from a one-time ticket minted by the apex OAuth callback.
//
// Task 10R fix 1 adds a browser-binding requirement: the request must also
// present the raw `owt_xdomain_guard` cookie value (set host-only by
// oauth-login.ts's custom-domain apex bounce) alongside the ticket, or this
// route must fail closed -- WITHOUT ever calling ssoExchange, never
// establishing a session from the ticket alone. That guard cookie is
// cleared on every outcome.
//
// We mock next/headers (cookies()) and @/services/auth.service so the route
// module can be imported and its GET handler invoked directly, mirroring the
// mock.module pattern used by route.test.ts (/auth/link/complete).

type CookieRecord = { value: string };
let requestCookies: Record<string, CookieRecord | undefined> = {};

mock.module("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => requestCookies[name]
  })
}));

type SsoExchangeCall = { ticket: string; guard: string };
const ssoExchangeCalls: SsoExchangeCall[] = [];
let ssoExchangeShouldThrow = false;
let ssoExchangeTokens = { access_token: "access-token-1", refresh_token: "refresh-token-1" };

mock.module("@/services/auth.service", () => ({
  authService: {
    ssoExchange: async (ticket: string, guard: string) => {
      ssoExchangeCalls.push({ ticket, guard });
      if (ssoExchangeShouldThrow) {
        throw new Error("boom");
      }
      return ssoExchangeTokens;
    }
  }
}));

const { GET } = await import("./route");

function req(url: string): Request {
  return new Request(url);
}

function withGuardCookie(value = "raw-guard-value"): void {
  requestCookies.owt_xdomain_guard = { value };
}

function setCookieHeaders(res: Response): string[] {
  return res.headers.getSetCookie ? res.headers.getSetCookie() : [];
}

describe("GET /auth/sso", () => {
  beforeEach(() => {
    requestCookies = {};
    ssoExchangeCalls.length = 0;
    ssoExchangeShouldThrow = false;
    ssoExchangeTokens = { access_token: "access-token-1", refresh_token: "refresh-token-1" };
  });

  afterEach(() => {
    requestCookies = {};
  });

  it("rejects a missing ticket without calling ssoExchange", async () => {
    const res = await GET(req("https://anakq.gg/auth/sso"));

    const location = new URL(res.headers.get("location")!);
    expect(location.origin).toBe("https://anakq.gg");
    expect(location.searchParams.get("auth_error")).toBe("invalid_state");
    expect(ssoExchangeCalls.length).toBe(0);
  });

  // Task 10R fix 1: the core fail-closed assertion. A valid ticket is
  // present but the guard cookie is absent (as it would be for an
  // attacker's ticket redeemed by the victim's own browser, which never
  // held the attacker's guard cookie) -- this must reject WITHOUT ever
  // calling ssoExchange, never establishing a session from the ticket alone.
  it("error-redirects and never calls ssoExchange when the guard cookie is absent (fail closed, even with a valid ticket)", async () => {
    // Deliberately no owt_xdomain_guard cookie.
    const res = await GET(req("https://anakq.gg/auth/sso?ticket=tic-1&next=%2Fdashboard"));

    const location = new URL(res.headers.get("location")!);
    expect(location.origin).toBe("https://anakq.gg");
    expect(location.searchParams.get("auth_error")).toBe("invalid_state");
    expect(ssoExchangeCalls.length).toBe(0);
  });

  it("forwards the raw guard cookie value to ssoExchange alongside the ticket", async () => {
    withGuardCookie("raw-guard-value-1");

    await GET(req("https://anakq.gg/auth/sso?ticket=tic-1&next=%2Fdashboard"));

    expect(ssoExchangeCalls).toEqual([{ ticket: "tic-1", guard: "raw-guard-value-1" }]);
  });

  it("establishes the session and clears the single-use guard cookie on success", async () => {
    withGuardCookie();

    const res = await GET(req("https://anakq.gg/auth/sso?ticket=tic-1&next=%2Fdashboard"));

    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("https://anakq.gg/dashboard");

    const cookies = setCookieHeaders(res);
    expect(cookies.some((c) => c.startsWith("owt_access_token=access-token-1;"))).toBe(true);
    expect(cookies.some((c) => c.startsWith("owt_refresh_token=refresh-token-1;"))).toBe(true);
    expect(cookies.some((c) => c.match(/^owt_xdomain_guard=;/))).toBe(true);
  });

  it("clamps an absolute cross-origin next to this origin's root (safeRedirectTarget)", async () => {
    withGuardCookie();

    const res = await GET(req("https://anakq.gg/auth/sso?ticket=tic-1&next=https%3A%2F%2Fevil.com%2Fsteal"));

    expect(res.headers.get("location")).toBe("https://anakq.gg/");
  });

  it("error-redirects (without leaking the error) when the ticket exchange fails, and still clears the guard cookie", async () => {
    withGuardCookie();
    ssoExchangeShouldThrow = true;

    const res = await GET(req("https://anakq.gg/auth/sso?ticket=tic-1&next=%2Fdashboard"));

    const location = new URL(res.headers.get("location")!);
    expect(location.origin).toBe("https://anakq.gg");
    expect(location.searchParams.get("auth_error")).toBe("exchange_failed");

    const cookies = setCookieHeaders(res);
    expect(cookies.length).toBe(1);
    expect(cookies[0]).toMatch(/^owt_xdomain_guard=;/);
  });
});
