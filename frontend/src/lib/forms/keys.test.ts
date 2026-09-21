import { describe, expect, it } from "bun:test";

import { makeUniqueFieldKey } from "@/lib/forms/keys";

/**
 * A key the server's `KEY_PATTERN` (`^[a-z][a-z0-9_]{0,31}$`) refuses is a
 * schema the organizer cannot save, and the failure surfaces as a `schema_invalid`
 * on a path they cannot act on — so the generator must never produce one.
 */
const KEY_PATTERN = /^[a-z][a-z0-9_]{0,31}$/;

describe("makeUniqueFieldKey", () => {
  it("derives a slug from the label", () => {
    expect(makeUniqueFieldKey("VK profile", [])).toBe("vk_profile");
    expect(makeUniqueFieldKey("Прочитал правила?", [])).toBe("field");
  });

  it("suffixes a taken key", () => {
    expect(makeUniqueFieldKey("VK profile", ["vk_profile"])).toBe("vk_profile_2");
    expect(makeUniqueFieldKey("VK profile", ["vk_profile", "vk_profile_2"])).toBe("vk_profile_3");
  });

  it("keeps a collision suffix inside the length cap", () => {
    // Two long labels agreeing on their first 32 characters: appending `_2`
    // past the cap would produce a 34-character key the schema validator
    // refuses, so the base gives way to the suffix instead.
    const label = "A very long registration question about something";
    const first = makeUniqueFieldKey(label, []);
    const second = makeUniqueFieldKey(label, [first]);
    expect(first).toHaveLength(32);
    expect(second).not.toBe(first);
    expect(second).toMatch(KEY_PATTERN);
    expect(second.endsWith("_2")).toBe(true);
  });

  it("produces a valid key from a label that cannot start one", () => {
    for (const label of ["2024 roster", "!!!", "", "   "]) {
      expect(makeUniqueFieldKey(label, [])).toMatch(KEY_PATTERN);
    }
  });
});
