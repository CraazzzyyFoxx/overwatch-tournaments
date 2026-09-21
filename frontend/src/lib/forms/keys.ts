/**
 * Field keys for the schema builder.
 *
 * A custom field's key is derived from its label ONCE, when the field is
 * created, and then locked: the key is what every stored answer is filed under,
 * so re-deriving it after a rename would orphan every answer already submitted.
 */

/** Shaped to the server's `KEY_PATTERN` (`^[a-z][a-z0-9_]{0,31}$`): a key it
 *  refuses is a schema the organizer cannot save. */
function slugifyKey(value: string): string {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "")
    .slice(0, 32);
  if (!slug) return "";
  return /^[a-z]/.test(slug) ? slug : `f_${slug}`.slice(0, 32);
}

/** A stable unique key for a new field, never derived again. */
export function makeUniqueFieldKey(label: string, existingKeys: Iterable<string>): string {
  const taken = new Set(existingKeys);
  const base = slugifyKey(label) || "field";
  if (!taken.has(base)) {
    return base;
  }
  let index = 2;
  while (taken.has(`${base}_${index}`)) {
    index += 1;
  }
  return `${base}_${index}`;
}
