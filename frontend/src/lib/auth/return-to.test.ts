import { describe, expect, it } from "vitest";

import { RETURN_TO_PARAM, safeReturnPath, withReturnTo } from "./return-to";

describe("safeReturnPath", () => {
  it("keeps a same-origin path", () => {
    expect(safeReturnPath("/tournaments/87/bracket?stage=5", "/fallback")).toBe(
      "/tournaments/87/bracket?stage=5"
    );
  });

  it("falls back when nothing was carried", () => {
    expect(safeReturnPath(null, "/fallback")).toBe("/fallback");
    expect(safeReturnPath("", "/fallback")).toBe("/fallback");
  });

  it("refuses anything that could leave the site", () => {
    // An open redirect is the whole risk of trusting a URL from the query string.
    for (const hostile of [
      "https://evil.example.com",
      "//evil.example.com/phish",
      "/\\evil.example.com",
      "javascript:alert(1)",
      "tournaments/87/bracket"
    ]) {
      expect(safeReturnPath(hostile, "/fallback")).toBe("/fallback");
    }
  });
});

describe("withReturnTo", () => {
  it("attaches the caller's location, encoded", () => {
    expect(withReturnTo("/tournaments/87/pregame/5986", "/tournaments/87/bracket?stage=5")).toBe(
      `/tournaments/87/pregame/5986?${RETURN_TO_PARAM}=%2Ftournaments%2F87%2Fbracket%3Fstage%3D5`
    );
  });

  it("appends to an href that already has a query", () => {
    expect(withReturnTo("/room?tab=maps", "/here")).toBe(
      `/room?tab=maps&${RETURN_TO_PARAM}=%2Fhere`
    );
  });
});
