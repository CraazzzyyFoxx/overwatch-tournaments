import { beforeEach, describe, expect, it, mock } from "bun:test";

// Mirrors the mock.module("next/headers", ...) pattern used by the
// /auth/sso route test — lets us drive the request header from the test.
let requestHeaders: Record<string, string | undefined> = {};

mock.module("next/headers", () => ({
  headers: async () => ({
    get: (name: string) => requestHeaders[name] ?? null,
  }),
}));

const { isTenantHost } = await import("./tenant-host");

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
