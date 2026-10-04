import { beforeEach, describe, expect, it, vi } from "vitest";

// Mirrors the vi.mock("next/headers", ...) pattern used by the
// /auth/sso route test — lets us drive the request header from the test.
let requestHeaders: Record<string, string | undefined> = {};

// bun's mock.module is process-global, so this replaces `next/headers` for the
// whole run. Export `cookies` too (a benign stub) so we don't strip an export
// other suites' modules import from next/headers.
vi.mock("next/headers", () => ({
  headers: async () => ({
    get: (name: string) => requestHeaders[name] ?? null,
  }),
  cookies: async () => ({
    get: () => undefined,
  }),
}));

const { isTenantHost, resolveStatsScope } = await import("./tenant-host");

describe("isTenantHost", () => {
  beforeEach(() => {
    requestHeaders = {};
  });

  it("returns true when x-owt-host-mode is 'tenant'", async () => {
    requestHeaders["x-owt-host-mode"] = "tenant";
    expect(await isTenantHost()).toBe(true);
  });

  it("returns false when the header is absent (platform host)", async () => {
    expect(await isTenantHost()).toBe(false);
  });

  it("returns false for any non-'tenant' value", async () => {
    requestHeaders["x-owt-host-mode"] = "platform";
    expect(await isTenantHost()).toBe(false);
  });
});

describe("resolveStatsScope", () => {
  beforeEach(() => {
    requestHeaders = {};
  });

  it("opts into all workspaces on the platform apex", async () => {
    expect(await resolveStatsScope("all")).toEqual({ scope: "all", available: true });
  });

  it("defaults to the workspace scope without the param", async () => {
    expect(await resolveStatsScope(undefined)).toEqual({ scope: "workspace", available: true });
  });

  it("ignores scope=all on a tenant host and hides the toggle", async () => {
    requestHeaders["x-owt-host-mode"] = "tenant";
    expect(await resolveStatsScope("all")).toEqual({ scope: "workspace", available: false });
  });
});
