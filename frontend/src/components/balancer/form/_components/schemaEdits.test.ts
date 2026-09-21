import { describe, expect, it } from "bun:test";

import type { FormField, FormSchema } from "@/types/forms.types";

import {
  blockedFieldKeys,
  fieldKeyAtSchemaPath,
  moveFieldOnto,
  moveFieldToSection,
  pruneStrandedConditions,
  removeField,
  renameField,
  sanitizeSchema
} from "./schemaEdits";

/**
 * The builder's half of `schema.py::_invariants`.
 *
 * Every rule below is one the server states as a `schema_invalid` 422 on a path
 * — `sections[1].fields[3].visible_when` — that an organizer cannot act on. The
 * editor's job is to make each one unreachable; these are the claims that it
 * does, without a DOM.
 */

function field(key: string, extra: Partial<FormField> = {}): FormField {
  return {
    key,
    kind: "text",
    label: key,
    help: null,
    placeholder: null,
    required: false,
    visibility: "public",
    options: null,
    validation: null,
    params: {},
    show_in_draft: false,
    ...extra
  };
}

function schemaOf(...sections: Array<[string, FormField[]]>): FormSchema {
  return {
    schema_version: 1,
    sections: sections.map(([key, fields]) => ({ key, title: null, description: null, fields }))
  };
}

/** `b` conditioned on `a`, in that order, across two sections. */
const CONDITIONED = schemaOf(
  ["one", [field("a"), field("b", { visible_when: { field: "a", op: "truthy" } })]],
  ["two", [field("c")]]
);

function conditionOf(schema: FormSchema, key: string) {
  return schema.sections.flatMap((s) => s.fields).find((f) => f.key === key)?.visible_when ?? null;
}

describe("pruneStrandedConditions", () => {
  it("leaves a condition that still points at an earlier field", () => {
    const { schema, cleared } = pruneStrandedConditions(CONDITIONED);
    expect(cleared).toEqual([]);
    // Same object back: an untouched schema must not re-render the editor.
    expect(schema).toBe(CONDITIONED);
  });

  it("clears a condition stranded by reordering within a section", () => {
    const moved = moveFieldOnto(CONDITIONED, "b", "a");
    const { schema, cleared } = pruneStrandedConditions(moved);
    expect(cleared).toEqual(["b"]);
    expect(conditionOf(schema, "b")).toBeNull();
  });

  it("clears a condition stranded by moving the target into a later section", () => {
    const moved = moveFieldToSection(CONDITIONED, "a", "two");
    const { schema, cleared } = pruneStrandedConditions(moved);
    expect(cleared).toEqual(["b"]);
    expect(conditionOf(schema, "b")).toBeNull();
  });

  it("clears a condition stranded by reordering sections", () => {
    const flipped: FormSchema = { ...CONDITIONED, sections: [...CONDITIONED.sections].reverse() };
    // `c` never had a condition and `b` still follows `a`, so nothing strands.
    expect(pruneStrandedConditions(flipped).cleared).toEqual([]);

    const conditionedAcross = schemaOf(
      ["one", [field("a")]],
      ["two", [field("b", { visible_when: { field: "a", op: "truthy" } })]]
    );
    const reversed: FormSchema = {
      ...conditionedAcross,
      sections: [...conditionedAcross.sections].reverse()
    };
    const { schema, cleared } = pruneStrandedConditions(reversed);
    expect(cleared).toEqual(["b"]);
    expect(conditionOf(schema, "b")).toBeNull();
  });

  it("clears a condition stranded by deleting its target", () => {
    const { schema, cleared } = pruneStrandedConditions(removeField(CONDITIONED, "a"));
    expect(cleared).toEqual(["b"]);
    expect(conditionOf(schema, "b")).toBeNull();
  });

  it("clears a condition a field somehow points at itself", () => {
    const selfish = schemaOf(["one", [field("a", { visible_when: { field: "a", op: "truthy" } })]]);
    expect(pruneStrandedConditions(selfish).cleared).toEqual(["a"]);
  });
});

describe("renameField", () => {
  it("follows the references a later field holds", () => {
    const renamed = renameField(CONDITIONED, "a", "asked_first");
    expect(renamed.sections[0].fields[0].key).toBe("asked_first");
    expect(conditionOf(renamed, "b")).toEqual({ field: "asked_first", op: "truthy" });
    // …and the rename must not strand what it just followed.
    expect(pruneStrandedConditions(renamed).cleared).toEqual([]);
  });
});

describe("moveFieldOnto", () => {
  it("reorders within a section and inserts across sections", () => {
    const within = moveFieldOnto(CONDITIONED, "b", "a");
    expect(within.sections[0].fields.map((f) => f.key)).toEqual(["b", "a"]);

    const across = moveFieldOnto(CONDITIONED, "a", "c");
    expect(across.sections[0].fields.map((f) => f.key)).toEqual(["b"]);
    expect(across.sections[1].fields.map((f) => f.key)).toEqual(["a", "c"]);
  });
});

describe("sanitizeSchema", () => {
  it("trims the copy and collapses what is empty", () => {
    const messy = schemaOf([
      "one",
      [
        field("q", {
          label: "  Which server?  ",
          help: "   ",
          placeholder: "",
          validation: { regex: "   ", error_message: "  nope  " }
        })
      ]
    ]);
    messy.sections[0].title = "  Details  ";
    messy.sections[0].description = "   ";

    const clean = sanitizeSchema(messy);
    expect(clean.sections[0].title).toBe("Details");
    expect(clean.sections[0].description).toBeNull();
    const only = clean.sections[0].fields[0];
    expect(only.label).toBe("Which server?");
    expect(only.help).toBeNull();
    expect(only.placeholder).toBeNull();
    expect(only.validation).toEqual({ regex: null, error_message: "nope" });
  });

  it("gives options only to the kinds that take them, trimmed and deduped", () => {
    const clean = sanitizeSchema(
      schemaOf([
        "one",
        [
          field("pick", { kind: "select", options: [" Twitch ", "", "YouTube", "Twitch"] }),
          field("free", { kind: "text", options: ["leftover"] })
        ]
      ])
    );
    expect(clean.sections[0].fields[0].options).toEqual(["Twitch", "YouTube"]);
    expect(clean.sections[0].fields[1].options).toBeNull();
  });

  it("strips params from a custom field and keeps a builtin's", () => {
    const clean = sanitizeSchema(
      schemaOf([
        "one",
        [
          field("mine", { params: { require_verified: true } }),
          field("battle_tag", { kind: "builtin", label: null, params: { require_verified: true } })
        ]
      ])
    );
    expect(clean.sections[0].fields[0].params).toEqual({});
    expect(clean.sections[0].fields[1].params).toEqual({ require_verified: true });
  });

  it("forces show_in_draft off where the server would refuse it", () => {
    const clean = sanitizeSchema(
      schemaOf([
        "one",
        [
          field("hidden", { visibility: "organizers", show_in_draft: true }),
          field("builtin_one", { kind: "builtin", key: "stream_pov", show_in_draft: true }),
          field("shown", { show_in_draft: true })
        ]
      ])
    );
    const drafted = clean.sections[0].fields.map((f) => f.show_in_draft);
    expect(drafted).toEqual([false, false, true]);
  });

  it("saves a missing editable flag as closed", () => {
    const clean = sanitizeSchema(
      schemaOf([
        "one",
        [
          // The fixture omits the key entirely — an imported or hand-edited
          // document does the same, and locked is the only safe reading.
          field("silent"),
          field("explicitly_open", { editable: true }),
          field("explicitly_shut", { editable: false })
        ]
      ])
    );
    expect(clean.sections[0].fields.map((f) => f.editable)).toEqual([false, true, false]);
  });
});

describe("blockedFieldKeys", () => {
  it("blocks a custom field whose key is reserved for a builtin", () => {
    // Reachable only from a template or an older client — `makeUniqueFieldKey`
    // cannot produce one — but the server refuses the whole document for it.
    const smuggled = schemaOf([
      "one",
      [field("battle_tag"), field("identity_card"), field("fine")]
    ]);
    expect([...blockedFieldKeys(smuggled)]).toEqual(["battle_tag", "identity_card"]);
  });

  it("blocks an unlabelled custom field, bad options and a broken pattern", () => {
    const broken = schemaOf([
      "one",
      [
        field("nameless", { label: "   " }),
        field("empty", { kind: "select", options: [] }),
        field("dupes", { kind: "multi_select", options: ["a", "a"] }),
        field("bad_regex", { validation: { regex: "([a-z", error_message: null } }),
        field("long_regex", { validation: { regex: `^${"a".repeat(300)}$`, error_message: null } })
      ]
    ]);
    expect([...blockedFieldKeys(broken)]).toEqual([
      "nameless",
      "empty",
      "dupes",
      "bad_regex",
      "long_regex"
    ]);
  });

  it("passes a schema the server would accept", () => {
    expect([...blockedFieldKeys(CONDITIONED)]).toEqual([]);
  });

  it("does not demand a label of a builtin", () => {
    const builtins = schemaOf([
      "one",
      [field("battle_tag", { kind: "builtin", label: null }), field("roles", { kind: "builtin", label: null })]
    ]);
    expect([...blockedFieldKeys(builtins)]).toEqual([]);
  });
});

describe("fieldKeyAtSchemaPath", () => {
  it("resolves a schema_invalid path to the field it names", () => {
    expect(fieldKeyAtSchemaPath(CONDITIONED, "sections[0].fields[1].visible_when")).toBe("b");
    expect(fieldKeyAtSchemaPath(CONDITIONED, "sections[1].fields[0].key")).toBe("c");
  });

  it("returns null for a path that names no field", () => {
    for (const path of ["sections[0].key", "sections[9].fields[0]", "sections[0].fields[7]", "roles"]) {
      expect(fieldKeyAtSchemaPath(CONDITIONED, path)).toBeNull();
    }
  });
});
