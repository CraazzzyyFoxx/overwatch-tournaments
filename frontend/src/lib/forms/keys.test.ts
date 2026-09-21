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

  it("never lands in the namespace the schema reserves for builtins", () => {
    // The reserved set does not depend on what the form currently asks: drop
    // the `battle_tag` builtin and a question labelled "Battle Tag" still may
    // not take its key, because `_invariants` refuses any non-builtin field
    // whose key is a builtin one or starts with `identity_`.
    expect(makeUniqueFieldKey("Battle Tag", [])).not.toBe("battle_tag");
    expect(makeUniqueFieldKey("Stream POV", [])).not.toBe("stream_pov");
    // A label that merely resembles one is left alone.
    expect(makeUniqueFieldKey("Notes", ["public_notes"])).toBe("notes");

    // Suffixing cannot escape a PREFIX — `identity_card_2` is still reserved —
    // so the escape has to happen at the front.
    for (const label of ["Identity card", "identity_discord", "Identity"]) {
      const key = makeUniqueFieldKey(label, []);
      expect(key.startsWith("identity_")).toBe(false);
      expect(key).toMatch(KEY_PATTERN);
    }
  });

  it("still disambiguates once a key has been escaped", () => {
    const first = makeUniqueFieldKey("Battle Tag", []);
    const second = makeUniqueFieldKey("Battle Tag", [first]);
    expect(second).not.toBe(first);
    expect(second).toMatch(KEY_PATTERN);
  });
});
