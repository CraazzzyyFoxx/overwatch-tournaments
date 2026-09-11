import { describe, expect, it } from "vitest";

import { isAuthRequiredPath } from "@/config/auth";

// A 401 on an auth-required path throws the visitor back to `/` with the
// sign-in modal open (`AuthBootstrap`). Mix boards are public, so they must
// answer `false` here even though they live under the `/balancer` prefix.
describe("isAuthRequiredPath", () => {
  it("keeps the admin and balancer tools behind a login", () => {
    expect(isAuthRequiredPath("/admin/workspaces")).toBe(true);
    expect(isAuthRequiredPath("/balancer/pool")).toBe(true);
  });

  it("leaves a signed-out visitor on a mix board", () => {
    expect(isAuthRequiredPath("/balancer/mix")).toBe(false);
    expect(isAuthRequiredPath("/balancer/mix/12")).toBe(false);
  });

  it("treats the rest of the site as public", () => {
    expect(isAuthRequiredPath("/tournaments")).toBe(false);
  });
});
