/**
 * Server rejections of a registration submission → per-field UI strings.
 *
 * Modelled on `registration-team-errors.ts` (§12.2): every backend `msg` is
 * English and this audience is Russian-first, so the stable machine `code` is
 * what gets translated and `msg` is only the last resort for a code this build
 * does not know yet.
 *
 * The same table serves client-side generic validation (`validate.ts`): the
 * client mirrors a subset of the server's rules, so it must speak the server's
 * codes rather than invent a parallel vocabulary.
 */

import { ApiError } from "@/lib/api-error";

/**
 * Every code a form write can return, grouped by origin. Generic codes are
 * emitted for any field — including `roles`, where "unknown hero" is an
 * `invalid_option` — so their copy must read sensibly on any field.
 */
export const FORM_ERROR_CODES = [
  // Generic, from `shared.domain.forms.validate.ErrorCode`.
  "required",
  "invalid_format",
  "invalid_type",
  "invalid_option",
  "too_many",
  "not_verified",
  "unknown_field",
  // Role composition, from the roles builtin.
  "roles.primary_required",
  "roles.additional_required",
  "roles.flex_unavailable",
  "roles.one_priority_or_flex",
  "roles.unknown_role",
  "roles.subrole_not_allowed",
  "roles.too_many_heroes",
  "roles.hero_wrong_class",
  // Form and schema level.
  "form_version_stale",
  "schema_invalid",
  // Templates.
  "template_name_taken",
  "template_not_found",
  "form_not_configured",
  // Not a server code: the fallback when the failure carried none.
  "request_failed",
] as const;

export type FormErrorCode = (typeof FORM_ERROR_CODES)[number];

/** Static membership table — nothing is inserted at runtime. */
const KNOWN_CODES: Record<string, true> = Object.fromEntries(
  FORM_ERROR_CODES.map((code) => [code, true] as const),
);

/**
 * A next-intl translator scoped to `forms.errors`.
 *
 * The key type is the code union, not `string`: the project types its messages,
 * so `useTranslations("forms.errors")` only accepts keys that exist — and a
 * narrow-key function is not assignable to a wide-key parameter. `has` is
 * optional so a plain function (or a test double) still works; without it the
 * code list above is the membership test, which is why it must stay exhaustive.
 */
export type Translate = ((key: FormErrorCode) => string) & {
  has?: (key: FormErrorCode) => boolean;
};

export interface FormErrors {
  /** Keyed by answer key (`battle_tag`, `roles`, a custom field key). */
  fields: Record<string, string>;
  /** The rejection that belongs to no single field. */
  form: string | null;
  /** The schema changed under the user: refetch the form and re-render. */
  stale: boolean;
}

/**
 * Split a thrown write failure into field messages, a form-level message and
 * the staleness flag.
 *
 * The FIRST error per field wins: the server reports every problem it found, and
 * a field with two of them shows the one it listed first rather than the last.
 */
export function fieldErrorsFrom(error: unknown, t: Translate): FormErrors {
  const result: FormErrors = { fields: {}, form: null, stale: false };
  if (!(error instanceof ApiError)) {
    result.form = t("request_failed");
    return result;
  }
  for (const detail of error.details) {
    // `detail.code` is an untyped wire string; the cast is safe because only a
    // code the dictionary holds is ever passed to `t`.
    const code = detail.code as FormErrorCode;
    const translatable = typeof t.has === "function" ? t.has(code) : KNOWN_CODES[code] === true;
    const message = translatable ? t(code) : detail.msg;
    if (code === "form_version_stale") result.stale = true;
    if (detail.field) {
      result.fields[detail.field] ??= message;
    } else {
      result.form ??= message;
    }
  }
  if (result.form === null && Object.keys(result.fields).length === 0) {
    result.form = t("request_failed");
  }
  return result;
}
