import { afterEach, beforeEach, describe, expect, it, mock } from "bun:test";

// /auth/link/complete (Task 10R) is the far side of the custom-domain
// account-linking end-ticket: it runs ON the workspace's custom domain and
// must (a) resolve the linked-to user ONLY from a live session cookie on
// THIS request -- never from the ticket or any URL/query value -- and (b)
// set NO cookies, since linking never changes the caller's session (unlike
// /auth/sso/route.ts, which DOES establish a session from its ticket).
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

type CompleteLinkCall = { ticket: string; accessToken: string };
const completeLinkCalls: CompleteLinkCall[] = [];
let completeLinkShouldThrow = false;

// safeRedirectTarget (imported by route.ts from @/lib/oauth-callback) in turn
// imports OAuthLinkAuthRequiredError from this module, so the mock below must
// re-export it (even though this test never throws it) or that import fails.
class OAuthLinkAuthRequiredError extends Error {}

mock.module("@/services/auth.service", () => ({
  OAuthLinkAuthRequiredError,
  authService: {
    completeLink: async (ticket: string, accessToken: string) => {
      completeLinkCalls.push({ ticket, accessToken });
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

  it("resolves the linked-to user ONLY from the live session cookie on this request", async () => {
    requestCookies.owt_access_token = { value: "session-token-abc" };

    await GET(req("https://anakq.gg/auth/link/complete?ticket=tic-1&next=%2Faccount"));

    expect(completeLinkCalls).toEqual([{ ticket: "tic-1", accessToken: "session-token-abc" }]);
  });

  it("redirects to the safe next target on success and sets no cookies", async () => {
    requestCookies.owt_access_token = { value: "session-token-abc" };

    const res = await GET(req("https://anakq.gg/auth/link/complete?ticket=tic-1&next=%2Faccount"));

    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("https://anakq.gg/account");
    // Session is unchanged by this request -- see module docstring.
    expect(res.headers.getSetCookie ? res.headers.getSetCookie() : []).toEqual([]);
  });

  it("clamps an absolute cross-origin next to this origin's root (safeRedirectTarget)", async () => {
    requestCookies.owt_access_token = { value: "session-token-abc" };

    const res = await GET(req("https://anakq.gg/auth/link/complete?ticket=tic-1&next=https%3A%2F%2Fevil.com%2Fsteal"));

    expect(res.headers.get("location")).toBe("https://anakq.gg/");
  });

  it("error-redirects (without leaking the error) when the ticket redeem fails", async () => {
    requestCookies.owt_access_token = { value: "session-token-abc" };
    completeLinkShouldThrow = true;

    const res = await GET(req("https://anakq.gg/auth/link/complete?ticket=tic-1&next=%2Faccount"));

    const location = new URL(res.headers.get("location")!);
    expect(location.origin).toBe("https://anakq.gg");
    expect(location.searchParams.get("auth_error")).toBe("exchange_failed");
  });
});
