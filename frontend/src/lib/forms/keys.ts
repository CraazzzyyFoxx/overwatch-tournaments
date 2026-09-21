/**
 * Field keys for the schema builder.
 *
 * A custom field's key is derived from its label ONCE, when the field is
 * created, and then locked: the key is what every stored answer is filed under,
 * so re-deriving it after a rename would orphan every answer already submitted.
 */

import { isReservedFieldKey } from "./builtin-keys";

/** `KEY_PATTERN` on the server: `^[a-z][a-z0-9_]{0,31}$`. */
const MAX_KEY_LENGTH = 32;

/** Shaped to the server's `KEY_PATTERN`: a key it refuses is a schema the
 *  organizer cannot save. */
function slugifyKey(value: string): string {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "")
    .slice(0, MAX_KEY_LENGTH);
  if (!slug) return "";
  return /^[a-z]/.test(slug) ? slug : `f_${slug}`.slice(0, MAX_KEY_LENGTH);
}

/**
 * A stable unique key for a new field, never derived again.
 *
 * Two namespaces have to be dodged, not one. `existingKeys` is what the form
 * asks RIGHT NOW; the builtin keys and the whole `identity_` prefix are
 * reserved whether or not the form currently uses them, because the schema
 * refuses a custom field on either. Dropping the `battle_tag` builtin and then
 * adding a question labelled "Battle Tag" would otherwise build a document the
 * server rejects on a path the organizer cannot act on.
 */
export function makeUniqueFieldKey(label: string, existingKeys: Iterable<string>): string {
  const taken = new Set(existingKeys);
  let base = slugifyKey(label) || "field";
  // Escaped rather than suffixed: `identity_card_2` is still inside the
  // reserved prefix, so numbering would never get out of it. `f_` is the same
  // escape `slugifyKey` uses for a slug that cannot start a key, and nothing
  // beginning with it can be reserved.
  if (isReservedFieldKey(base)) base = `f_${base}`.slice(0, MAX_KEY_LENGTH);
  if (!taken.has(base)) {
    return base;
  }
  // The suffix has to fit INSIDE the cap, not be appended past it: two long
  // labels agreeing on their first 32 characters would otherwise produce a
  // 34-character key the schema validator refuses.
  for (let index = 2; ; index += 1) {
    const suffix = `_${index}`;
    const candidate = base.slice(0, MAX_KEY_LENGTH - suffix.length) + suffix;
    if (!taken.has(candidate)) return candidate;
  }
}
