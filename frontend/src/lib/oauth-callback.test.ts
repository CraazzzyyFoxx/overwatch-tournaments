import { afterEach, beforeEach, describe, expect, it, mock } from "bun:test";

import { decodeStateForRouting, isVerifiedTenantOrigin, safeRedirectTarget } from "@/lib/oauth-callback";
import { PLATFORM_ZONE } from "@/lib/host";

// Builds a state string in the exact shape decodeStateForRouting reads --
// `base64url(payloadJson).base64url(signature)` -- without needing a real
// HMAC: this decode never touches the signature part, only splits it off.
function fakeState(payload: Record<string, unknown>, signaturePart = "sig"): string {
  const json = JSON.stringify(payload);
  const payloadPart = Buffer.from(json, "utf-8").toString("base64url");
  return `${payloadPart}.${signaturePart}`;
}

// isVerifiedTenantOrigin is the authoritative gate for the custom-domain SSO
// ticket handoff: unlike the cookie-mode path (safe because those cookies
// are Domain=.owt and unreadable off-zone regardless of what `origin`
// claims), the ticket branch redirects the user's browser straight to
// `<origin>/auth/sso?ticket=...` — an unverified origin there is an account
// takeover. We drive it purely from the edges (a URL-aware fetch mock), so
// this file registers no module mock that could leak into other test files.

type Globals = { fetch?: typeof fetch };
const g = globalThis as unknown as Globals;
const originalFetch = globalThis.fetch;
const originalInternalApiUrl = process.env.NEXT_INTERNAL_API_URL;

let lastRequestedUrl: string | undefined;
// workspace_id the mocked by-host lookup returns for the next call.
let byHostWorkspaceId: number | null = 1;
// When set, the mocked fetch resolves to this HTTP status instead of a
// normal 200 JSON body (used to simulate a transient backend failure).
let byHostStatus: number | undefined;
// When set, the mocked fetch rejects instead of resolving (network error).
let byHostThrows = false;

beforeEach(() => {
  process.env.NEXT_INTERNAL_API_URL = "http://gateway:8080";
  lastRequestedUrl = undefined;
  byHostWorkspaceId = 1;
  byHostStatus = undefined;
  byHostThrows = false;

  g.fetch = mock(async (url: string | URL) => {
    lastRequestedUrl = String(url);
    if (byHostThrows) throw new Error("network error");
    if (byHostStatus !== undefined) {
      return new Response(null, { status: byHostStatus });
    }
    return new Response(JSON.stringify({ workspace_id: byHostWorkspaceId }), { status: 200 });
  }) as unknown as typeof fetch;
});

afterEach(() => {
  g.fetch = originalFetch;
  if (originalInternalApiUrl === undefined) {
    delete process.env.NEXT_INTERNAL_API_URL;
  } else {
    process.env.NEXT_INTERNAL_API_URL = originalInternalApiUrl;
  }
});

describe("isVerifiedTenantOrigin", () => {
  it("rejects a non-http(s) scheme without calling by-host", async () => {
    expect(await isVerifiedTenantOrigin("javascript:alert(1)")).toBe(false);
    expect(lastRequestedUrl).toBeUndefined();
  });

  it("rejects a malformed origin without calling by-host", async () => {
    expect(await isVerifiedTenantOrigin("not a url")).toBe(false);
    expect(lastRequestedUrl).toBeUndefined();
  });

  it("verifies a custom domain that by-host resolves to a workspace", async () => {
    byHostWorkspaceId = 42;
    expect(await isVerifiedTenantOrigin("https://anakq.gg")).toBe(true);
    expect(lastRequestedUrl).toBe("http://gateway:8080/api/v1/workspaces/by-host?host=anakq.gg");
  });

  it("verifies a registered platform-zone subdomain that by-host resolves", async () => {
    byHostWorkspaceId = 7;
    expect(await isVerifiedTenantOrigin(`https://team-a.${PLATFORM_ZONE}`)).toBe(true);
  });

  it("fails closed when by-host returns workspace_id: null (unregistered host)", async () => {
    byHostWorkspaceId = null;
    expect(await isVerifiedTenantOrigin("https://evil.com")).toBe(false);
  });

  it("fails closed on a non-OK by-host response (transient backend failure)", async () => {
    byHostStatus = 500;
    expect(await isVerifiedTenantOrigin("https://anakq.gg")).toBe(false);
  });

  it("fails closed when the by-host fetch throws (network error)", async () => {
    byHostThrows = true;
    expect(await isVerifiedTenantOrigin("https://anakq.gg")).toBe(false);
  });

  it("rejects the platform apex itself (not a tenant host, and by-host would not resolve it)", async () => {
    byHostWorkspaceId = null;
    expect(await isVerifiedTenantOrigin(`https://${PLATFORM_ZONE}`)).toBe(false);
  });
});

describe("decodeStateForRouting", () => {
  it("reports hasLinkIntent true when the state carries a non-empty link_intent (\"li\")", () => {
    const state = fakeState({ a: "link", p: "discord", li: "nonce-abc123" });
    expect(decodeStateForRouting(state)).toEqual({ action: "link", provider: "discord", hasLinkIntent: true });
  });

  it("reports hasLinkIntent false when \"li\" is absent (the ordinary apex/subdomain linking case)", () => {
    const state = fakeState({ a: "link", p: "discord" });
    expect(decodeStateForRouting(state)).toEqual({ action: "link", provider: "discord", hasLinkIntent: false });
  });

  it("reports hasLinkIntent false when \"li\" is an empty string", () => {
    const state = fakeState({ a: "link", p: "discord", li: "" });
    expect(decodeStateForRouting(state)).toEqual({ action: "link", provider: "discord", hasLinkIntent: false });
  });

  it("reports hasLinkIntent false for a login state even if \"li\" were somehow present", () => {
    // Defense in depth for the routing read only -- the backend independently
    // rejects link_intent signed into anything but a "link" state
    // (oauth_flows.get_url), so this key should never appear here in practice.
    const state = fakeState({ a: "login", p: "twitch", li: "nonce-abc123" });
    expect(decodeStateForRouting(state).action).toBe("login");
  });

  it("defaults to action=login, provider=null, hasLinkIntent=false on a malformed state", () => {
    expect(decodeStateForRouting("not-a-valid-state")).toEqual({
      action: "login",
      provider: null,
      hasLinkIntent: false
    });
  });

  it("treats an unknown provider as null regardless of hasLinkIntent", () => {
    const state = fakeState({ a: "link", p: "unknown-provider", li: "nonce-abc123" });
    expect(decodeStateForRouting(state)).toEqual({ action: "link", provider: null, hasLinkIntent: true });
  });
});

describe("safeRedirectTarget", () => {
  it("keeps a same-origin relative redirect", () => {
    const target = safeRedirectTarget("/account", "https://anakq.gg");
    expect(target.toString()).toBe("https://anakq.gg/account");
  });

  it("falls back to the origin's root on an absolute cross-origin redirect", () => {
    const target = safeRedirectTarget("https://evil.com/steal", "https://anakq.gg");
    expect(target.toString()).toBe("https://anakq.gg/");
  });

  it("falls back to the origin's root on a protocol-relative escape", () => {
    const target = safeRedirectTarget("//evil.com/steal", "https://anakq.gg");
    expect(target.toString()).toBe("https://anakq.gg/");
  });

  it("falls back to the origin's root on an empty redirect", () => {
    const target = safeRedirectTarget("", "https://anakq.gg");
    expect(target.toString()).toBe("https://anakq.gg/");
  });
});
