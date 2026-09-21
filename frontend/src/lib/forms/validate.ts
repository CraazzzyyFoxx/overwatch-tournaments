/**
 * Client-side answer validation: the GENERIC rules only.
 *
 * A thin mirror of step 2 of `shared/domain/forms/validate.py::normalize_answers`
 * — required, format, options, number/date shape. Deliberately NOT mirrored:
 * builtin behaviour (verified accounts, the identity catalog) and role
 * composition. Those need server state, the server rejects them with the same
 * codes this module speaks, and a second copy of a rule is a rule that drifts.
 *
 * Returning `null` therefore means "nothing the client can see is wrong", never
 * "the server will accept this".
 */

import type { Translate } from "@/lib/forms/form-errors";
import type { FormField } from "@/types/forms.types";

/**
 * Patterns applied when a field declares no `validation.regex`, mirroring
 * `shared.domain.forms.builtins.DEFAULT_PATTERNS`. Keyed by field key first,
 * then by kind — exactly like `default_pattern`.
 */
const DEFAULT_PATTERNS: Record<string, string> = {
  battle_tag: String.raw`([^#]{2,12}#[0-9]{4,})`,
  smurf_tags: String.raw`([^#]{2,12}#[0-9]{4,})`,
  identity_discord: String.raw`^[a-z0-9_.]{2,32}$`,
  identity_twitch: String.raw`^[a-zA-Z0-9_]{4,25}$`,
  identity_boosty: String.raw`^[^#]{2,50}$`,
  url: String.raw`^https?://.+$`,
};

/** A number as typed by a human: `1,5` is the Russian decimal separator. */
const NUMBER = /^-?\d+(?:[.,]\d+)?$/;
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** The strings a pattern actually runs on: a list answer is matched tag by tag. */
function patternTargets(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === "string").map((i) => i.trim());
  }
  return typeof value === "string" ? [value.trim()] : [];
}

/**
 * The field's pattern as a FULL-match regex.
 *
 * Python matches with `fullmatch`; JS has no such mode, so the pattern is
 * wrapped. The group is non-capturing so a top-level alternation still anchors
 * as a whole, and stored `^…$` anchors survive the wrapping unchanged.
 */
function compilePattern(field: FormField): RegExp | null {
  const pattern =
    field.validation?.regex || DEFAULT_PATTERNS[field.key] || DEFAULT_PATTERNS[field.kind];
  if (!pattern) return null;
  try {
    return new RegExp(`^(?:${pattern})$`);
  } catch {
    // The schema refuses an uncompilable regex at save time; a row stored before
    // that invariant existed is the server's problem to report, not a reason to
    // block the user here.
    return null;
  }
}

function isRealDate(value: string): boolean {
  const match = ISO_DATE.exec(value);
  if (!match) return false;
  const [, year, month, day] = match;
  const date = new Date(`${value}T00:00:00Z`);
  return (
    !Number.isNaN(date.getTime()) &&
    date.getUTCFullYear() === Number(year) &&
    date.getUTCMonth() + 1 === Number(month) &&
    date.getUTCDate() === Number(day)
  );
}

/**
 * The message to show under `field`, or `null` when the client has no objection.
 *
 * Checks run in the server's order — shape, then required, then format — so the
 * two never disagree about WHICH complaint a bad answer earns.
 */
export function validateAnswer(field: FormField, value: unknown, t: Translate): string | null {
  const empty =
    value === null ||
    value === undefined ||
    value === "" ||
    (Array.isArray(value) && value.length === 0);

  // An unchecked required checkbox is a missing answer, not a wrong type.
  if (empty || value === false) {
    return field.required ? t("required") : null;
  }

  const options = field.options ?? [];
  switch (field.kind) {
    case "number":
      if (typeof value !== "number" && !(typeof value === "string" && NUMBER.test(value.trim()))) {
        return t("invalid_type");
      }
      break;
    case "date":
      if (typeof value !== "string" || !isRealDate(value.trim())) return t("invalid_type");
      break;
    case "checkbox":
      if (typeof value !== "boolean") return t("invalid_type");
      break;
    case "select":
      if (typeof value !== "string") return t("invalid_type");
      if (!options.includes(value.trim())) return t("invalid_option");
      break;
    case "multi_select": {
      if (!Array.isArray(value)) return t("invalid_type");
      const unknown = value.some(
        (item) => typeof item !== "string" || !options.includes(item.trim()),
      );
      if (unknown) return t("invalid_option");
      break;
    }
    default:
      break;
  }

  const compiled = compilePattern(field);
  if (compiled) {
    const bad = patternTargets(value).some((target) => !compiled.test(target));
    if (bad) return field.validation?.error_message || t("invalid_format");
  }
  return null;
}
