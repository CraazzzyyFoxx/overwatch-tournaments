import { describe, expect, it } from "bun:test";

import { decodePlayerSlug, getPlayerSlug } from "@/utils/player";

describe("player slug helpers", () => {
  it("decodes percent-encoded battle tags from route slugs", () => {
    expect(decodePlayerSlug("%D0%A5%D0%BB%D0%BE%D1%80%D0%BE%D1%84%D0%BE%D1%80%D0%BC-21713")).toBe(
      "Хлороформ#21713"
    );
  });

  it("round-trips plain battle tags", () => {
    expect(decodePlayerSlug(getPlayerSlug("CraazzzyyFox#2130"))).toBe("CraazzzyyFox#2130");
  });

  it("falls back gracefully on malformed percent-encoding", () => {
    expect(decodePlayerSlug("%E0%A4%A-21713")).toBe("%E0%A4%A#21713");
  });
});
