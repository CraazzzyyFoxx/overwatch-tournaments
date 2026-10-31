import { describe, expect, it } from "vitest";

import type { AdminAuthSession } from "@/types/rbac.types";

import { accountsHref, formatDeviceLabel } from "./model";

const WINDOWS_CHROME =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36";

describe("formatDeviceLabel", () => {
  it("names the browser and the platform when it can read both", () => {
    expect(formatDeviceLabel(WINDOWS_CHROME, "Unknown")).toBe("Chrome · Windows");
    expect(formatDeviceLabel("Firefox/130.0", "Unknown")).toBe("Firefox");
    expect(formatDeviceLabel("Linux x86_64", "Unknown")).toBe("Linux");
  });

  it("falls back to the raw agent, cut at 64 characters", () => {
    expect(formatDeviceLabel(null, "Unknown")).toBe("Unknown");
    expect(formatDeviceLabel("curl/8.0", "Unknown")).toBe("curl/8.0");
    expect(formatDeviceLabel("x".repeat(70), "Unknown")).toBe(`${"x".repeat(64)}…`);
  });
});

describe("accountsHref", () => {
  it("searches accounts by email, then by username, and opens the account", () => {
    const session = { email: "a+b@x.io", username: "ab", user_id: 7 } as AdminAuthSession;
    expect(accountsHref(session)).toBe("/admin/access/accounts?search=a%2Bb%40x.io&id=7");
    expect(accountsHref({ ...session, email: null })).toBe("/admin/access/accounts?search=ab&id=7");
  });
});
