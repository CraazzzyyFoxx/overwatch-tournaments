import { beforeEach, describe, expect, it, mock } from "bun:test";
import { PLATFORM_ZONE } from "@/lib/host";

// oauth-login.ts's custom-domain apex bounce is the START of the Task 10R
// fix 1 browser-binding: it mints the guard token `G`, sets it in a
// host-only `owt_xdomain_guard` cookie on THIS custom domain, and carries
// only `H = sha256_hex(G)` onward as a `guard_hash` query param to the apex.
// These tests assert the properties the rest of the chain (oauth_service.py,
// oauth_flows.py, sso_tickets/pending_link_tickets, sso_exchange/
// link_complete) depend on: the cookie is host-only (no `domain` attribute,
// under ANY NODE_ENV), the raw value never appears in the bounce URL, and
// the query param really is that cookie's SHA-256 hash -- for BOTH the
// login and link actions. It also asserts the apex-side gate: guard_hash is
// only ever read (and forwarded to getOAuthUrl) on the platform apex itself,
// never on a subdomain, mirroring the existing `origin` gate.

type GetOAuthUrlCall = {
  provider: string;
  origin: string;
  redirect: string;
  action: string;
  csrf: string;
  guardHash: string | undefined;
};
const getOAuthUrlCalls: GetOAuthUrlCall[] = [];
let getOAuthUrlResult = { provider: "discord", url: "https://discord.example/authorize", state: "signed-state" };

mock.module("@/services/auth.service", () => ({
  authService: {
    getOAuthUrl: async (
      provider: string,
      params: { origin: string; redirect: string; action: string; csrf: string; guardHash?: string }
    ) => {
      getOAuthUrlCalls.push({ provider, ...params, guardHash: params.guardHash });
      return getOAuthUrlResult;
    }
  }
}));

const { startOAuthLogin } = await import("./oauth-login");

function req(url: string): Request {
  return new Request(url);
}

function setCookieHeaders(res: Response): string[] {
  return res.headers.getSetCookie ? res.headers.getSetCookie() : [];
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

describe("startOAuthLogin", () => {
  beforeEach(() => {
    getOAuthUrlCalls.length = 0;
    getOAuthUrlResult = { provider: "discord", url: "https://discord.example/authorize", state: "signed-state" };
  });

  describe("custom-domain bounce (onCustomDomain)", () => {
    for (const action of ["login", "link"] as const) {
      it(`sets a host-only owt_xdomain_guard cookie and a matching guard_hash on the apex bounce (action=${action})`, async () => {
        const qs = action === "link" ? "?action=link" : "";
        const res = await startOAuthLogin(req(`https://anakq.gg/auth/discord/login${qs}`), "discord");

        expect(res.status).toBe(307);
        const location = new URL(res.headers.get("location")!);
        expect(location.origin).toBe(`https://${PLATFORM_ZONE}`);
        expect(location.pathname).toBe("/auth/discord/login");
        expect(location.searchParams.get("action")).toBe(action);
        expect(location.searchParams.get("origin")).toBe("https://anakq.gg");

        const cookies = setCookieHeaders(res);
        const guardCookie = cookies.find((c) => c.startsWith("owt_xdomain_guard="));
        expect(guardCookie).toBeDefined();
        // Host-only: NEVER a `domain=` attribute, on this cookie, in ANY
        // environment -- see the module docstring for why (a domain-wide
        // guard cookie would defeat the whole binding).
        expect(guardCookie!.toLowerCase()).not.toContain("domain=");

        const rawGuard = guardCookie!.split(";")[0].split("=")[1];
        expect(rawGuard.length).toBeGreaterThanOrEqual(32);

        // The raw guard value never appears in the bounce URL -- only its hash.
        const bounceUrl = res.headers.get("location")!;
        expect(bounceUrl).not.toContain(rawGuard);

        const expectedHash = await sha256Hex(rawGuard);
        expect(location.searchParams.get("guard_hash")).toBe(expectedHash);

        // The apex re-invokes startOAuthLogin itself -- getOAuthUrl must
        // never be called directly from this bounce.
        expect(getOAuthUrlCalls.length).toBe(0);
      });
    }

    it("carries the next param through the bounce", async () => {
      const res = await startOAuthLogin(req("https://anakq.gg/auth/discord/login?next=%2Fsettings"), "discord");
      const location = new URL(res.headers.get("location")!);
      expect(location.searchParams.get("next")).toBe("/settings");
    });

    it("mints a fresh guard token (and hash) on every bounce", async () => {
      const first = await startOAuthLogin(req("https://anakq.gg/auth/discord/login"), "discord");
      const second = await startOAuthLogin(req("https://anakq.gg/auth/discord/login"), "discord");

      const firstHash = new URL(first.headers.get("location")!).searchParams.get("guard_hash");
      const secondHash = new URL(second.headers.get("location")!).searchParams.get("guard_hash");
      expect(firstHash).not.toBe(secondHash);
    });
  });

  describe("apex (guard_hash gate)", () => {
    it("forwards a bounced guard_hash query param to getOAuthUrl", async () => {
      const res = await startOAuthLogin(
        req(`https://${PLATFORM_ZONE}/auth/discord/login?action=login&origin=https%3A%2F%2Fanakq.gg&guard_hash=abc123`),
        "discord"
      );

      expect(res.status).toBe(307);
      expect(getOAuthUrlCalls.length).toBe(1);
      expect(getOAuthUrlCalls[0].guardHash).toBe("abc123");
      expect(getOAuthUrlCalls[0].origin).toBe("https://anakq.gg");
    });

    it("omits guardHash entirely when no guard_hash param is present (platform-host flow)", async () => {
      await startOAuthLogin(req(`https://${PLATFORM_ZONE}/auth/discord/login`), "discord");

      expect(getOAuthUrlCalls.length).toBe(1);
      expect(getOAuthUrlCalls[0].guardHash).toBeUndefined();
    });
  });

  describe("subdomain (never honors guard_hash)", () => {
    it("never reads guard_hash on a non-apex platform subdomain, even if supplied", async () => {
      const res = await startOAuthLogin(
        req(`https://team-a.${PLATFORM_ZONE}/auth/discord/login?guard_hash=attacker-supplied`),
        "discord"
      );

      expect(res.status).toBe(307);
      expect(getOAuthUrlCalls.length).toBe(1);
      expect(getOAuthUrlCalls[0].guardHash).toBeUndefined();
      // And it must not have gone through the custom-domain bounce either --
      // no guard cookie set on a `.owt` subdomain.
      expect(setCookieHeaders(res).some((c) => c.startsWith("owt_xdomain_guard="))).toBe(false);
    });
  });
});
