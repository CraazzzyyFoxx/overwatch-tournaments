/**
 * Typed reads off a stored `answers` document.
 *
 * `Answers` is `Record<string, unknown>` because a field's kind decides what
 * its value is, and the document carries no kinds. A consumer that wants one
 * concrete answer — the smurf list for a clipboard copy, a handle for a chip,
 * the stream-POV flag for a badge — needs the same three coercions every time,
 * and writing them inline is how five slightly different `String(x ?? "")`
 * casts come to exist.
 *
 * Every helper answers "is there an answer of this shape here", never "was this
 * field asked": a public read is stripped to the public keys of the
 * registration's OWN form version, so an absent key means not asked, not
 * answered, or not yours to read. Use `key in answers` where that distinction
 * matters (the stream-POV badge does).
 *
 * Rendering an answer of an arbitrary kind is `components/forms/AnswerValue`;
 * this module is for the handful of places that need the raw value typed.
 */

import type { Answers } from "@/types/forms.types";

/**
 * The document itself may be missing.
 *
 * Every read model DECLARES `answers` and the server always sends it, so this
 * is not a shape the types admit — but these helpers sit under table cells and
 * roster chips, where one row whose document never arrived (a hand-written
 * fixture, a cached response from an older build, a partial row a sheet import
 * wrote) must read as "no answer", not take the whole screen down with a
 * `TypeError`. The guard lives here rather than at the call sites precisely so
 * there is ONE of it.
 */
type AnswerDocument = Answers | null | undefined;

/** A non-empty text answer, or `null`. Numbers stringify; nothing else does. */
export function answerText(answers: AnswerDocument, key: string): string | null {
  const value = answers?.[key];
  if (typeof value === "string") return value.trim() === "" ? null : value;
  if (typeof value === "number") return String(value);
  return null;
}

/** A list answer (`smurf_tags`, `multi_select`) as strings; `[]` when absent. */
export function answerList(answers: AnswerDocument, key: string): string[] {
  const value = answers?.[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

/** A checkbox answer. `"false"` reads as false — a form encoding may round-trip
 *  a boolean through a string, and a non-empty string is otherwise truthy. */
export function answerFlag(answers: AnswerDocument, key: string): boolean {
  const value = answers?.[key];
  return value === true || value === "true";
}

/** One answer as search text, or `null` when there is nothing to match on.
 *  `false` is not searchable: an unticked checkbox is not something anybody
 *  types into a search box, and every row without the tick would match "false". */
export function answerSearchText(value: unknown): string | null {
  if (value === null || value === undefined || value === "" || value === false) return null;
  if (Array.isArray(value)) return value.join(" ") || null;
  return String(value);
}
