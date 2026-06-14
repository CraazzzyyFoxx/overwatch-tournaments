import { describe, expect, it } from "bun:test";

import { getCurrentPathForAuthRedirect } from "@/lib/auth-redirect";

describe("getCurrentPathForAuthRedirect", () => {
  it("returns pathname, search, and hash for the current location", () => {
    expect(
      getCurrentPathForAuthRedirect({
        pathname: "/tournaments/42",
        search: "?tab=participants",
        hash: "#registration",
      })
    ).toBe("/tournaments/42?tab=participants#registration");
  });

  it("falls back to root when pathname is missing or invalid", () => {
    expect(
      getCurrentPathForAuthRedirect({
        pathname: "",
        search: "?tab=participants",
        hash: "",
      })
    ).toBe("/?tab=participants");

    expect(
      getCurrentPathForAuthRedirect({
        pathname: "tournaments/42",
        search: "",
        hash: "",
      })
    ).toBe("/");
  });
});
