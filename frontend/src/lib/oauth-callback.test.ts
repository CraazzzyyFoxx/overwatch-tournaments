import { afterEach, beforeEach, describe, expect, it, mock } from "bun:test";

import { buildLinkTicketRedirect, isVerifiedTenantOrigin, safeRedirectTarget } from "@/lib/oauth-callback";
import { PLATFORM_ZONE } from "@/lib/host";

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

// buildLinkTicketRedirect is the Task 10R analogue of the ticket-mode branch
// tested above for login: it must gate delivery of the account-linking
// end-ticket through the SAME by_host verification, fail-closed. A ticket
// delivered to an unverified/attacker origin would let its operator link the
// victim's provider identity to their own account (see the module's security
// invariants), so this is exactly as load-bearing as the login ticket gate.
describe("buildLinkTicketRedirect", () => {
  it("returns null when the origin fails by-host verification (fail closed)", async () => {
    byHostWorkspaceId = null;
    expect(await buildLinkTicketRedirect("https://evil.com", "tic-1", "/account")).toBeNull();
    // The gate itself ran (and rejected) -- it did not skip straight to
    // building the URL without checking.
    expect(lastRequestedUrl).toBe("http://gateway:8080/api/v1/workspaces/by-host?host=evil.com");
  });

  it("returns null when the by-host fetch throws (network error)", async () => {
    byHostThrows = true;
    expect(await buildLinkTicketRedirect("https://anakq.gg", "tic-1", "/account")).toBeNull();
  });

  it("builds the /auth/link/complete URL only after by-host verification succeeds", async () => {
    byHostWorkspaceId = 42;
    const url = await buildLinkTicketRedirect("https://anakq.gg", "tic-1", "/account");
    expect(url?.toString()).toBe("https://anakq.gg/auth/link/complete?ticket=tic-1&next=%2Faccount");
  });

  it("defaults the redirect to /account when redirect is empty", async () => {
    byHostWorkspaceId = 42;
    const url = await buildLinkTicketRedirect("https://anakq.gg", "tic-1", "");
    expect(url?.searchParams.get("next")).toBe("/account");
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
