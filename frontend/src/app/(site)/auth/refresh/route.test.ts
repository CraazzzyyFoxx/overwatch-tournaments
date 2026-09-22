import { beforeEach, describe, expect, it, mock } from "bun:test";

// POST /auth/refresh is the ONLY way a browser turns the httpOnly refresh cookie
// into a fresh access token. Clearing that cookie is therefore irreversible for
// the client: it is a forced re-login. So the route must clear it for exactly one
// reason -- the upstream said 401 (token missing/expired/revoked) -- and never for
// a transient failure.
//
// The regression this pins: a VPN/network switch changes the client IP mid-flight
// (in-flight request dies) or a shared VPN/NAT exit IP burns the per-IP auth
// throttle (429). Both used to land in a bare `catch` that answered 401 AND wiped
// the cookies, silently logging out every VPN user.

import { ApiError } from "@/lib/api/error";

let requestCookies: Record<string, { value: string } | undefined> = {};

mock.module("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => requestCookies[name]
  })
}));

let refreshOutcome: (() => Promise<{ access_token: string; refresh_token: string }>) | null = null;

// `bun test` shares one module registry across the files in a run, so whichever
// mock of this module registers first is the one every other auth-route test
// sees. Re-export the link-error classes here too -- @/lib/auth/oauth-callback
// imports them, and a mock missing either name takes the sibling route tests
// down with a SyntaxError at import time.
mock.module("@/services/auth.service", () => ({
  OAuthLinkAuthRequiredError: class extends Error {},
  OAuthLinkFailedError: class extends Error {},
  authService: {
    refresh: async () => refreshOutcome!()
  }
}));
// Dynamic import (not static): mock.module must register before the route module
// evaluates its `next/headers` / auth.service imports. Same pattern as
// ../sso/route.test.ts.
const { POST } = await import("./route");

function req(): Request {
  return new Request("https://tenant.example.com/auth/refresh", { method: "POST" });
}

function clearedCookieNames(res: Response): string[] {
  const headers = res.headers.getSetCookie ? res.headers.getSetCookie() : [];
  // A cleared cookie is sent back empty (Max-Age=0 / Expires in the past).
  return headers
    .filter((header) => /^[^=]+=(;|$)/.test(header) || /Max-Age=0/i.test(header))
    .map((header) => header.split("=")[0]);
}

describe("POST /auth/refresh", () => {
  beforeEach(() => {
    requestCookies = { owt_refresh_token: { value: "refresh-token-1" } };
    refreshOutcome = null;
  });

  it("rotates the cookies on success", async () => {
    refreshOutcome = async () => ({ access_token: "access-2", refresh_token: "refresh-2" });

    const res = await POST(req());

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ access_token: "access-2", refresh_token: "refresh-2" });
    expect(clearedCookieNames(res)).toEqual([]);
  });

  it("clears the session cookies only on an upstream 401", async () => {
    refreshOutcome = async () => {
      throw new ApiError(401, [{ msg: "Invalid or expired refresh token", code: "unauthorized" }]);
    };

    const res = await POST(req());

    expect(res.status).toBe(401);
    expect(clearedCookieNames(res)).toContain("owt_refresh_token");
  });

  it("keeps the session cookies when the auth throttle answers 429", async () => {
    refreshOutcome = async () => {
      throw new ApiError(429, [{ msg: "Too many requests", code: "too_many_requests" }]);
    };

    const res = await POST(req());

    expect(res.status).toBe(503);
    expect(clearedCookieNames(res)).toEqual([]);
  });

  it("keeps the session cookies when the request dies at the network level", async () => {
    refreshOutcome = async () => {
      throw new TypeError("fetch failed");
    };

    const res = await POST(req());

    expect(res.status).toBe(503);
    expect(clearedCookieNames(res)).toEqual([]);
  });

  it("clears the session cookies when no refresh cookie is present", async () => {
    requestCookies = {};

    const res = await POST(req());

    expect(res.status).toBe(401);
    expect(clearedCookieNames(res)).toContain("owt_refresh_token");
  });
});
