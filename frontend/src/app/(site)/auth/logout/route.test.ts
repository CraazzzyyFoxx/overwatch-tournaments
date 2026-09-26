import { beforeEach, describe, expect, it, vi } from "vitest";

// Logout must (a) never be reachable by GET — a state change on a GET is
// something link previews, security scanners and speculative prefetch trigger
// for you — and (b) always clear BOTH session cookies in BOTH scopes, whatever
// the upstream revoke did. A logout that leaves the cookies behind is a user who
// believes they signed out on a shared computer and did not.

let requestCookies: Record<string, { value: string } | undefined> = {};

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => requestCookies[name]
  })
}));

// `bun test` shares one module registry across a run, so this mock must carry
// every export the sibling auth-route tests rely on (see the note in
// ../refresh/route.test.ts) — whichever file registers first wins.
vi.mock("@/services/auth.service", () => ({
  OAuthLinkAuthRequiredError: class extends Error {},
  OAuthLinkFailedError: class extends Error {},
  authService: {
    logout: async () => undefined,
    refresh: async () => ({ access_token: "a", refresh_token: "r" })
  }
}));

// Dynamic import (not static): mock.module must register before the route module
// evaluates its `next/headers` / auth.service imports.
const routeModule = await import("./route");

function req(): Request {
  return new Request("https://tenant.example.com/auth/logout", { method: "POST" });
}

function clearedCookieNames(res: Response): string[] {
  const headers = res.headers.getSetCookie ? res.headers.getSetCookie() : [];
  // A cleared cookie comes back empty (Max-Age=0 / Expires in the past).
  return headers
    .filter((header) => /^[^=]+=(;|$)/.test(header) || /Max-Age=0/i.test(header))
    .map((header) => header.split("=")[0]);
}

describe("POST /auth/logout", () => {
  beforeEach(() => {
    requestCookies = {
      owt_access_token: { value: "access-1" },
      owt_refresh_token: { value: "refresh-1" }
    };
  });

  it("answers 204 and clears both session cookies", async () => {
    const res = await routeModule.POST(req());

    expect(res.status).toBe(204);
    expect(await res.text()).toBe("");
    const cleared = clearedCookieNames(res);
    expect(cleared).toContain("owt_access_token");
    expect(cleared).toContain("owt_refresh_token");
  });

  it("still clears the cookies when there is no session to revoke upstream", async () => {
    requestCookies = {};

    const res = await routeModule.POST(req());

    expect(res.status).toBe(204);
    const cleared = clearedCookieNames(res);
    expect(cleared).toContain("owt_access_token");
    expect(cleared).toContain("owt_refresh_token");
  });

  it("exposes no GET handler, so nothing can log a user out by fetching a URL", () => {
    expect("GET" in routeModule).toBe(false);
  });
});
