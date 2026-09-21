import { describe, expect, it } from "bun:test";

import en from "@/i18n/messages/en.json";
import ru from "@/i18n/messages/ru.json";
import { ApiError, type ApiErrorDetail } from "@/lib/api-error";
import { FORM_ERROR_CODES, fieldErrorsFrom, type Translate } from "@/lib/forms/form-errors";

/**
 * A rejected submission must land on the field that caused it, in Russian.
 *
 * `messages.parity.test.ts` proves en and ru agree with each other; the last
 * describe here is what ties the CODE list to the dictionaries, so adding a
 * server rejection without translating it fails here rather than shipping
 * English server text to a Russian user (§12.2).
 */

/** Marks translated strings so an assertion can tell them from a raw `msg`. */
const t: Translate = Object.assign((key: string) => `ru:${key}`, {
  has: (key: string) => (FORM_ERROR_CODES as readonly string[]).includes(key),
}) as Translate;

function apiError(status: number, ...details: ApiErrorDetail[]) {
  return new ApiError(status, details);
}

describe("fieldErrorsFrom", () => {
  it("keeps two rejections of two fields apart", () => {
    const result = fieldErrorsFrom(
      apiError(
        422,
        { code: "required", msg: "This field is required.", field: "battle_tag" },
        { code: "invalid_option", msg: "Not one of the options.", field: "server" },
      ),
      t,
    );
    expect(result.fields).toEqual({
      battle_tag: "ru:required",
      server: "ru:invalid_option",
    });
    expect(result.form).toBeNull();
    expect(result.stale).toBe(false);
  });

  it("shows the first rejection of a field, not the last", () => {
    const result = fieldErrorsFrom(
      apiError(
        422,
        { code: "required", msg: "first", field: "roles" },
        { code: "invalid_option", msg: "second", field: "roles" },
      ),
      t,
    );
    expect(result.fields.roles).toBe("ru:required");
  });

  it("falls back to the server's msg for a code this build does not know", () => {
    const result = fieldErrorsFrom(
      apiError(422, { code: "brand_new_rule", msg: "Server said no.", field: "q1" }),
      t,
    );
    expect(result.fields.q1).toBe("Server said no.");
  });

  it("sends a detail with no field to the form level", () => {
    const result = fieldErrorsFrom(
      apiError(409, { code: "template_name_taken", msg: "Name taken." }),
      t,
    );
    expect(result.fields).toEqual({});
    expect(result.form).toBe("ru:template_name_taken");
  });

  it("flags a 409 form_version_stale and shows it at the form level", () => {
    // The real payload names `form_version_id` as its field — a REQUEST key,
    // never an answer key, so it must not be filed under `fields` where no
    // renderer looks for it.
    const result = fieldErrorsFrom(
      apiError(409, {
        code: "form_version_stale",
        msg: "The form changed.",
        field: "form_version_id",
      }),
      t,
    );
    expect(result.stale).toBe(true);
    expect(result.form).toBe("ru:form_version_stale");
    expect(result.fields).toEqual({});
  });

  it("still reports something when the failure is not an ApiError", () => {
    const result = fieldErrorsFrom(new TypeError("Failed to fetch"), t);
    expect(result).toEqual({ fields: {}, form: "ru:request_failed", stale: false });
  });
});

describe("form error codes", () => {
  it("every code has a translation in both locales", () => {
    const missing = (dict: typeof en | typeof ru) =>
      FORM_ERROR_CODES.filter((code) => {
        // Codes are dotted paths (`roles.unknown_role`), which next-intl reads
        // as nesting, so the lookup walks the tree rather than indexing once.
        const leaf = code.split(".").reduce<unknown>((node, part) => {
          if (!node || typeof node !== "object") return undefined;
          return (node as Record<string, unknown>)[part];
        }, dict.forms.errors);
        return typeof leaf !== "string";
      });
    expect({ en: missing(en), ru: missing(ru) }).toEqual({ en: [], ru: [] });
  });
});
