import { afterEach, beforeEach, describe, expect, it, mock } from "bun:test";

// /auth/link/complete (Task 10R) is the far side of the custom-domain
// account-linking end-ticket: it runs ON the workspace's custom domain and
// must (a) resolve the linked-to user ONLY from a live session cookie on
// THIS request -- never from the ticket or any URL/query value -- and (b)
// set no SESSION cookies, since linking never changes the caller's session
// (unlike /auth/sso/route.ts, which DOES establish a session from its
// ticket).
//
// Task 10R fix 1 adds a THIRD requirement: the request must also present the
// raw `owt_xdomain_guard` cookie value (set host-only by oauth-login.ts's
// custom-domain apex bounce) alongside the ticket, or this route must fail
// closed -- WITHOUT ever calling completeLink -- even when a valid ticket
// and a valid bearer session are both present. That guard cookie is cleared
// on every outcome (it IS a cookie this route sets/clears, unlike a session
// cookie).
//
// We mock next/headers (cookies()) and @/services/auth.service so the route
// module can be imported and its GET handler invoked directly, mirroring the
// mock.module pattern used by me.service.test.ts.

type CookieRecord = { value: string };
let requestCookies: Record<string, CookieRecord | undefined> = {};

mock.module("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => requestCookies[name]
  })
}));

type CompleteLinkCall = { ticket: string; accessToken: string; guard: string };
const completeLinkCalls: CompleteLinkCall[] = [];
let completeLinkShouldThrow = false;

// safeRedirectTarget (imported by route.ts from @/lib/oauth-callback) in turn
// imports OAuthLinkAuthRequiredError from this module, so the mock below must
// re-export it (even though this test never throws it) or that import fails.
class OAuthLinkAuthRequiredError extends Error {}

mock.module("@/services/auth.service", () => ({
  OAuthLinkAuthRequiredError,
  authService: {
    completeLink: async (ticket: string, accessToken: string, guard: string) => {
      completeLinkCalls.push({ ticket, accessToken, guard });
      if (completeLinkShouldThrow) {
        throw new Error("boom");
      }
      return { message: "Discord account linked successfully", provider: "discord", username: "u" };
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

describe("GET /auth/link/complete", () => {
  beforeEach(() => {
    requestCookies = {};
    completeLinkCalls.length = 0;
    completeLinkShouldThrow = false;
  });

  afterEach(() => {
    requestCookies = {};
  });

  it("redirects to login and does not call completeLink when there is no live session", async () => {
    const res = await GET(req("https://anakq.gg/auth/link/complete?ticket=tic-1&next=%2Faccount"));

    expect(res.status).toBe(307);
    const location = new URL(res.headers.get("location")!);
    expect(location.origin).toBe("https://anakq.gg");
    expect(location.pathname).toBe("/");
    expect(location.searchParams.get("login")).toBe("1");
    expect(completeLinkCalls.length).toBe(0);
  });

  it("rejects a missing ticket without calling completeLink", async () => {
    requestCookies.owt_access_token = { value: "session-token" };

    const res = await GET(req("https://anakq.gg/auth/link/complete"));

    const location = new URL(res.headers.get("location")!);
    expect(location.searchParams.get("auth_error")).toBe("invalid_state");
    expect(completeLinkCalls.length).toBe(0);
  });

  // Task 10R fix 1: the core fail-closed assertion. A valid ticket AND a
  // valid bearer session are both present, but the guard cookie is absent
  // (as it would be for an attacker's ticket redeemed by the victim's own
  // browser, which never held the attacker's guard cookie) -- this must
  // reject WITHOUT ever calling completeLink, never falling back to linking
  // on the strength of the bearer alone.
  it("error-redirects and never calls completeLink when the guard cookie is absent (fail closed, even with a valid ticket + bearer)", async () => {
    requestCookies.owt_access_token = { value: "session-token-abc" };
    // Deliberately no owt_xdomain_guard cookie.

    const res = await GET(req("https://anakq.gg/auth/link/complete?ticket=tic-1&next=%2Faccount"));

    const location = new URL(res.headers.get("location")!);
    expect(location.origin).toBe("https://anakq.gg");
    expect(location.searchParams.get("auth_error")).toBe("invalid_state");
    expect(completeLinkCalls.length).toBe(0);
  });

  it("resolves the linked-to user ONLY from the live session cookie on this request, and forwards the raw guard cookie value", async () => {
    requestCookies.owt_access_token = { value: "session-token-abc" };
    withGuardCookie("raw-guard-value-1");

    await GET(req("https://anakq.gg/auth/link/complete?ticket=tic-1&next=%2Faccount"));

    expect(completeLinkCalls).toEqual([
      { ticket: "tic-1", accessToken: "session-token-abc", guard: "raw-guard-value-1" }
    ]);
  });

  it("redirects to the safe next target on success, sets no session cookies, and clears the single-use guard cookie", async () => {
    requestCookies.owt_access_token = { value: "session-token-abc" };
    withGuardCookie();

    const res = await GET(req("https://anakq.gg/auth/link/complete?ticket=tic-1&next=%2Faccount"));

    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("https://anakq.gg/account");
    // Session is unchanged by this request -- see module docstring. The
    // guard cookie IS cleared, so it's the only Set-Cookie present.
    const setCookies = res.headers.getSetCookie ? res.headers.getSetCookie() : [];
    expect(setCookies.length).toBe(1);
    expect(setCookies[0]).toMatch(/^owt_xdomain_guard=;/);
  });

  it("clears the guard cookie on the login-redirect path too (no live session)", async () => {
    const res = await GET(req("https://anakq.gg/auth/link/complete?ticket=tic-1&next=%2Faccount"));

    const setCookies = res.headers.getSetCookie ? res.headers.getSetCookie() : [];
    expect(setCookies.length).toBe(1);
    expect(setCookies[0]).toMatch(/^owt_xdomain_guard=;/);
  });

  it("clamps an absolute cross-origin next to this origin's root (safeRedirectTarget)", async () => {
    requestCookies.owt_access_token = { value: "session-token-abc" };
    withGuardCookie();

    const res = await GET(req("https://anakq.gg/auth/link/complete?ticket=tic-1&next=https%3A%2F%2Fevil.com%2Fsteal"));

    expect(res.headers.get("location")).toBe("https://anakq.gg/");
  });

  it("error-redirects (without leaking the error) when the ticket redeem fails, and still clears the guard cookie", async () => {
    requestCookies.owt_access_token = { value: "session-token-abc" };
    withGuardCookie();
    completeLinkShouldThrow = true;

    const res = await GET(req("https://anakq.gg/auth/link/complete?ticket=tic-1&next=%2Faccount"));

    const location = new URL(res.headers.get("location")!);
    expect(location.origin).toBe("https://anakq.gg");
    expect(location.searchParams.get("auth_error")).toBe("exchange_failed");
    const setCookies = res.headers.getSetCookie ? res.headers.getSetCookie() : [];
    expect(setCookies.length).toBe(1);
    expect(setCookies[0]).toMatch(/^owt_xdomain_guard=;/);
  });
});
