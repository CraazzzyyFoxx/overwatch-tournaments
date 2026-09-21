import { describe, expect, it } from "bun:test";

import type { FormErrorCode, Translate } from "@/lib/forms/form-errors";
import { validateAnswer } from "@/lib/forms/validate";
import type { FormField } from "@/types/forms.types";

/**
 * The client mirrors the server's GENERIC rules only, so these cases are the
 * ones a user must not have to round-trip to learn: a blank required answer, a
 * malformed handle, an option that is not on the list.
 */

/** Echoes the code, so an assertion names the rule that fired. */
const t: Translate = (key: FormErrorCode) => key;

function field(overrides: Partial<FormField> & Pick<FormField, "key" | "kind">): FormField {
  return {
    required: false,
    visibility: "public",
    params: {},
    show_in_draft: false,
    ...overrides,
  };
}

describe("validateAnswer — required", () => {
  it("refuses an unchecked required checkbox, not merely a missing one", () => {
    const rules = field({ key: "tos", kind: "checkbox", required: true });
    expect(validateAnswer(rules, false, t)).toBe("required");
    expect(validateAnswer(rules, undefined, t)).toBe("required");
    expect(validateAnswer(rules, true, t)).toBeNull();
  });

  it("lets an optional field be blank in every empty shape", () => {
    const rules = field({ key: "notes", kind: "text" });
    for (const value of [null, undefined, "", [], false]) {
      expect(validateAnswer(rules, value, t)).toBeNull();
    }
  });

  it("refuses a blank required answer before looking at its format", () => {
    expect(validateAnswer(field({ key: "notes", kind: "text", required: true }), "", t)).toBe(
      "required",
    );
  });
});

describe("validateAnswer — patterns", () => {
  const discord = field({ key: "identity_discord", kind: "builtin" });

  it("applies the server's default pattern when the field declares none", () => {
    expect(validateAnswer(discord, "good_name.1", t)).toBeNull();
    expect(validateAnswer(discord, "Bad Name!", t)).toBe("invalid_format");
  });

  it("matches the whole answer, never a substring", () => {
    // `^https?://.+$` is anchored, but `([^#]{2,12}#[0-9]{4,})` is not: Python
    // matches it with `fullmatch`, so trailing junk must still be rejected.
    const battleTag = field({ key: "battle_tag", kind: "builtin" });
    expect(validateAnswer(battleTag, "Player#1234", t)).toBeNull();
    expect(validateAnswer(battleTag, "Player#1234 and more", t)).toBe("invalid_format");
  });

  it("checks every tag of a list answer", () => {
    const smurfs = field({ key: "smurf_tags", kind: "builtin" });
    expect(validateAnswer(smurfs, ["Alt#1111", "Alt2#2222"], t)).toBeNull();
    expect(validateAnswer(smurfs, ["Alt#1111", "nope"], t)).toBe("invalid_format");
  });

  it("prefers the field's own error_message over the generic one", () => {
    const rules = field({
      key: "identity_discord",
      kind: "builtin",
      validation: { error_message: "Discord handles are lowercase." },
    });
    expect(validateAnswer(rules, "Bad Name!", t)).toBe("Discord handles are lowercase.");
  });

  it("uses an explicit regex instead of the default", () => {
    const rules = field({
      key: "identity_discord",
      kind: "builtin",
      validation: { regex: String.raw`^[A-Z]+$` },
    });
    expect(validateAnswer(rules, "ABC", t)).toBeNull();
    expect(validateAnswer(rules, "abc", t)).toBe("invalid_format");
  });

  it("stays silent when the stored regex cannot compile", () => {
    const rules = field({ key: "q", kind: "text", validation: { regex: "([unclosed" } });
    expect(validateAnswer(rules, "anything", t)).toBeNull();
  });
});

describe("validateAnswer — kinds", () => {
  it("refuses a value that is not one of the options", () => {
    const rules = field({ key: "server", kind: "select", options: ["eu", "na"] });
    expect(validateAnswer(rules, "eu", t)).toBeNull();
    expect(validateAnswer(rules, "asia", t)).toBe("invalid_option");
  });

  it("refuses a multi-select holding anything unlisted", () => {
    const rules = field({ key: "days", kind: "multi_select", options: ["mon", "tue"] });
    expect(validateAnswer(rules, ["mon", "tue"], t)).toBeNull();
    expect(validateAnswer(rules, ["mon", "sun"], t)).toBe("invalid_option");
  });

  it("accepts a human-typed number, including the Russian decimal separator", () => {
    const rules = field({ key: "age", kind: "number" });
    expect(validateAnswer(rules, "18", t)).toBeNull();
    expect(validateAnswer(rules, "1,5", t)).toBeNull();
    expect(validateAnswer(rules, 18, t)).toBeNull();
    expect(validateAnswer(rules, "eighteen", t)).toBe("invalid_type");
  });

  it("accepts only a real ISO date", () => {
    const rules = field({ key: "born", kind: "date" });
    expect(validateAnswer(rules, "2026-02-28", t)).toBeNull();
    expect(validateAnswer(rules, "2026-02-31", t)).toBe("invalid_type");
    expect(validateAnswer(rules, "28.02.2026", t)).toBe("invalid_type");
  });

  it("applies the url default pattern by kind", () => {
    const rules = field({ key: "vod", kind: "url" });
    expect(validateAnswer(rules, "https://twitch.tv/x", t)).toBeNull();
    expect(validateAnswer(rules, "twitch.tv/x", t)).toBe("invalid_format");
  });
});
