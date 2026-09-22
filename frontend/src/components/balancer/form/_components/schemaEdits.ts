/**
 * The schema editor's pure half: every edit the builder makes to a `FormSchema`,
 * and every rule it refuses to send one for.
 *
 * Separate from the components because none of it is React and all of it is the
 * part worth testing directly — the server's invariants (`schema.py::_invariants`)
 * are mirrored here, and a mirror that drifts is a 422 on a path the organizer
 * cannot act on. The editor never mutates: each function returns a new schema,
 * which is what makes the builder's "draft ?? the server's" a one-line decision.
 */

import { arrayMove } from "@dnd-kit/sortable";

import {
  builtinParamsKind,
  isBuiltinKey,
  isReservedFieldKey,
  type BuiltinFieldKey
} from "@/lib/forms/builtin-keys";
import type { FormField, FormSchema } from "@/types/forms.types";

const OPTION_KINDS: Record<string, true> = { select: true, multi_select: true };

/** The server compiles a pattern at save time and caps it; see `shared.core.social`. */
export const MAX_REGEX_LENGTH = 256;

/** Kinds and builtin keys whose answer is a string a pattern can run on. */
const VALIDATABLE_KINDS: Record<string, true> = {
  text: true,
  textarea: true,
  url: true,
  number: true
};
const VALIDATABLE_KEYS: Record<string, true> = { battle_tag: true, smurf_tags: true };

// ---------------------------------------------------------------------------
// Reading a schema
// ---------------------------------------------------------------------------

/** Every field in the order the wizard asks them — the order the server's
 *  `visible_when` invariant is stated in. */
export function flatFields(schema: FormSchema): FormField[] {
  return schema.sections.flatMap((section) => section.fields);
}

function locate(schema: FormSchema, key: string): { si: number; fi: number } | null {
  for (let si = 0; si < schema.sections.length; si += 1) {
    const fi = schema.sections[si].fields.findIndex((field) => field.key === key);
    if (fi !== -1) return { si, fi };
  }
  return null;
}

/** The fields asked BEFORE `key` — the only legal `visible_when` targets. */
export function earlierFields(schema: FormSchema, key: string): FormField[] {
  const flat = flatFields(schema);
  const index = flat.findIndex((field) => field.key === key);
  return index <= 0 ? [] : flat.slice(0, index);
}

export function supportsValidation(field: FormField): boolean {
  if (field.kind === "builtin") {
    return VALIDATABLE_KEYS[field.key] === true || builtinParamsKind(field.key) === "identity";
  }
  return VALIDATABLE_KINDS[field.kind] === true;
}

/**
 * What a field is called in the rail, the row and the `visible_when` picker.
 *
 * `builtinLabel` is `useTranslations("registrationFormAdmin.builtins")`. Its key
 * type is the literal union of that dictionary's keys, so the parameter takes
 * the same union rather than `string`: a wide-key parameter would refuse the
 * translator, and a cast at every call site would hide a key that has no copy.
 */
export function fieldDisplayLabel(
  field: FormField,
  builtinLabel: (key: BuiltinFieldKey) => string
): string {
  if (field.kind === "builtin" && isBuiltinKey(field.key)) return builtinLabel(field.key);
  return (field.label ?? "").trim() || field.key;
}

// ---------------------------------------------------------------------------
// Editing a schema
// ---------------------------------------------------------------------------

function withSections(
  schema: FormSchema,
  map: (fields: FormField[], index: number) => FormField[]
): FormSchema {
  return {
    ...schema,
    sections: schema.sections.map((section, index) => ({
      ...section,
      fields: map(section.fields, index)
    }))
  };
}

export function replaceField(schema: FormSchema, key: string, next: FormField): FormSchema {
  return withSections(schema, (fields) =>
    fields.some((field) => field.key === key)
      ? fields.map((field) => (field.key === key ? next : field))
      : fields
  );
}

export function appendField(
  schema: FormSchema,
  sectionKey: string,
  field: FormField
): FormSchema {
  return {
    ...schema,
    sections: schema.sections.map((section) =>
      section.key === sectionKey ? { ...section, fields: [...section.fields, field] } : section
    )
  };
}

export function removeField(schema: FormSchema, key: string): FormSchema {
  return withSections(schema, (fields) => fields.filter((field) => field.key !== key));
}

/**
 * Rename a field and follow its references.
 *
 * Only ever called for a field whose key is still provisional (a custom one the
 * organizer has not named yet), but a later field may already point at it, and
 * a dangling `visible_when` is a 422 rather than a warning.
 */
export function renameField(schema: FormSchema, from: string, to: string): FormSchema {
  return withSections(schema, (fields) =>
    fields.map((field) => {
      const renamed = field.key === from ? { ...field, key: to } : field;
      return renamed.visible_when?.field === from
        ? { ...renamed, visible_when: { ...renamed.visible_when, field: to } }
        : renamed;
    })
  );
}

/** Move `key` onto `overKey`'s slot, across sections when they differ. */
export function moveFieldOnto(schema: FormSchema, key: string, overKey: string): FormSchema {
  const from = locate(schema, key);
  const to = locate(schema, overKey);
  if (!from || !to) return schema;
  if (from.si === to.si) {
    return withSections(schema, (fields, index) =>
      index === from.si ? arrayMove(fields, from.fi, to.fi) : fields
    );
  }
  const field = schema.sections[from.si].fields[from.fi];
  return withSections(schema, (fields, index) => {
    if (index === from.si) return fields.filter((candidate) => candidate.key !== key);
    if (index !== to.si) return fields;
    const next = [...fields];
    next.splice(to.fi, 0, field);
    return next;
  });
}

/** Move `key` to the end of `sectionKey` — the rail rows are drop targets so a
 *  field can reach a section that is not on screen. */
export function moveFieldToSection(
  schema: FormSchema,
  key: string,
  sectionKey: string
): FormSchema {
  const from = locate(schema, key);
  if (!from || schema.sections[from.si].key === sectionKey) return schema;
  const field = schema.sections[from.si].fields[from.fi];
  return {
    ...schema,
    sections: schema.sections.map((section, index) => {
      if (index === from.si) {
        return { ...section, fields: section.fields.filter((candidate) => candidate.key !== key) };
      }
      return section.key === sectionKey
        ? { ...section, fields: [...section.fields, field] }
        : section;
    })
  };
}

/**
 * Drop every `visible_when` that no longer points at an EARLIER field.
 *
 * A reorder, a cross-section move or a deletion can strand a condition, and the
 * server rejects the whole schema when one is. Refusing the drop would make
 * dragging feel broken for a rule the organizer cannot see; keeping the stale
 * condition would fail the save with a path nobody can read. So the condition
 * is CLEARED and the caller says which questions lost one — the edit lands, and
 * nothing changes silently.
 */
export function pruneStrandedConditions(schema: FormSchema): {
  schema: FormSchema;
  cleared: string[];
} {
  const seen = new Set<string>();
  const cleared: string[] = [];
  const next = withSections(schema, (fields) =>
    fields.map((field) => {
      const target = field.visible_when?.field;
      const stranded = target !== undefined && (target === field.key || !seen.has(target));
      seen.add(field.key);
      if (!stranded) return field;
      cleared.push(field.key);
      return { ...field, visible_when: null };
    })
  );
  return cleared.length === 0 ? { schema, cleared } : { schema: next, cleared };
}

/**
 * The schema as it goes on the wire: trimmed copy, empty parts dropped.
 *
 * The editor keeps what the organizer typed — a trailing blank line in the
 * options box is a line they are about to fill — and this is where that becomes
 * a document the server's invariants accept.
 */
export function sanitizeSchema(schema: FormSchema): FormSchema {
  return {
    ...schema,
    sections: schema.sections.map((section) => ({
      ...section,
      title: section.title?.trim() || null,
      description: section.description?.trim() || null,
      fields: section.fields.map((field) => {
        const isBuiltin = field.kind === "builtin";
        const regex = field.validation?.regex?.trim() || null;
        const message = field.validation?.error_message?.trim() || null;
        return {
          ...field,
          label: isBuiltin ? (field.label ?? null) : (field.label ?? "").trim(),
          help: field.help?.trim() || null,
          placeholder: field.placeholder?.trim() || null,
          options: OPTION_KINDS[field.kind]
            ? [...new Set((field.options ?? []).map((option) => option.trim()).filter(Boolean))]
            : null,
          validation: regex || message ? { regex, error_message: message } : null,
          params: isBuiltin ? field.params : {},
          // Optional on the wire and closed by default, so an imported or
          // hand-edited schema cannot reach the save as `undefined` and leave
          // the server's default deciding what the organizer meant.
          editable: field.editable === true
        };
      })
    }))
  };
}

// ---------------------------------------------------------------------------
// Refusing to send one
// ---------------------------------------------------------------------------

export type FieldIssueCode =
  | "labelRequired"
  | "keyReserved"
  | "optionsRequired"
  | "optionsDuplicate"
  | "regexInvalid"
  | "regexTooLong";

export interface FieldIssues {
  label: FieldIssueCode | null;
  key: FieldIssueCode | null;
  options: FieldIssueCode | null;
  regex: FieldIssueCode | null;
}

/**
 * The server invariants this field currently violates.
 *
 * Reported as codes rather than copy so the SAVE path and the editor can share
 * one implementation: the builder blocks the mutation on any issue, the editor
 * translates the same codes under the control that caused them. A rule that
 * only the button knew about would be a disabled button with no explanation.
 */
export function fieldIssues(field: FormField): FieldIssues {
  const issues: FieldIssues = { label: null, key: null, options: null, regex: null };

  if (field.kind !== "builtin") {
    if (!(field.label ?? "").trim()) issues.label = "labelRequired";
    // `makeUniqueFieldKey` cannot produce one of these, but a template or a
    // schema written by an older client can carry one, and the server refuses
    // the whole document rather than the field.
    if (isReservedFieldKey(field.key)) issues.key = "keyReserved";
  }

  if (OPTION_KINDS[field.kind]) {
    const options = (field.options ?? []).map((option) => option.trim()).filter(Boolean);
    if (options.length === 0) issues.options = "optionsRequired";
    else if (new Set(options).size !== options.length) issues.options = "optionsDuplicate";
  }

  const regex = field.validation?.regex?.trim();
  if (regex) {
    if (regex.length > MAX_REGEX_LENGTH) {
      issues.regex = "regexTooLong";
    } else {
      try {
        // Compiled here for the same reason the server compiles it on save: a
        // pattern that cannot run must never reach a submission. The server
        // runs Python `re`, so the two dialects can disagree on an exotic
        // pattern — this catches the common typo, and a survivor still comes
        // back as a `schema_invalid` filed against this field.
        new RegExp(regex);
      } catch {
        issues.regex = "regexInvalid";
      }
    }
  }

  return issues;
}

/** Fields the editor itself refuses to send. The save button reports the count;
 *  each row and the field editor show the reason under the control. */
export function blockedFieldKeys(schema: FormSchema): Set<string> {
  const blocked = new Set<string>();
  for (const field of flatFields(schema)) {
    const issues = fieldIssues(field);
    if (issues.label || issues.key || issues.options || issues.regex) blocked.add(field.key);
  }
  return blocked;
}

/** `sections[1].fields[3].visible_when` → the key of the field it names.
 *  `schema_invalid` reports a PATH, and a path is not something to show an
 *  organizer; the field it points at is. */
export function fieldKeyAtSchemaPath(schema: FormSchema, path: string): string | null {
  const match = /^sections\[(\d+)]\.fields\[(\d+)]/.exec(path);
  if (!match) return null;
  return schema.sections[Number(match[1])]?.fields[Number(match[2])]?.key ?? null;
}
