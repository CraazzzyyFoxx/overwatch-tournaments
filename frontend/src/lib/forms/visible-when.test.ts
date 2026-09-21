import { describe, expect, it } from "bun:test";

import { evaluateCondition, visibleFields } from "@/lib/forms/visible-when";
import type { Condition, FormField, FormSchema } from "@/types/forms.types";

/**
 * The client half of `visible_when`. Every case here mirrors the server's
 * `test_evaluate_condition_ops`: the two evaluators decide what is asked and
 * what is required respectively, so a disagreement is a submission the user
 * cannot complete and cannot see why.
 */

function cond(op: Condition["op"], field: string, value?: unknown): Condition {
  return { field, op, value };
}

function field(key: string, visible_when: Condition | null = null): FormField {
  return {
    key,
    kind: "text",
    required: false,
    visibility: "public",
    params: {},
    show_in_draft: false,
    visible_when,
  };
}

describe("evaluateCondition", () => {
  it("treats a missing answer as falsy without throwing", () => {
    expect(evaluateCondition(cond("truthy", "absent"), {})).toBe(false);
    expect(evaluateCondition(cond("eq", "absent", "x"), {})).toBe(false);
    // Nothing equals nothing: an absent answer IS not-"x".
    expect(evaluateCondition(cond("neq", "absent", "x"), {})).toBe(true);
    expect(evaluateCondition(cond("in", "absent", ["x"]), {})).toBe(false);
  });

  it("counts the round-tripped string \"false\" as falsy", () => {
    // A checkbox that went through a form encoding arrives as "false".
    expect(evaluateCondition(cond("truthy", "a"), { a: "false" })).toBe(false);
    expect(evaluateCondition(cond("truthy", "a"), { a: "False" })).toBe(false);
    expect(evaluateCondition(cond("truthy", "a"), { a: " false " })).toBe(false);
    expect(evaluateCondition(cond("truthy", "a"), { a: "0" })).toBe(false);
    expect(evaluateCondition(cond("truthy", "a"), { a: "" })).toBe(false);
    expect(evaluateCondition(cond("truthy", "a"), { a: "true" })).toBe(true);
    expect(evaluateCondition(cond("truthy", "a"), { a: "no" })).toBe(true);
  });

  it("is falsy for the other empty answers", () => {
    for (const value of [0, null, [], false]) {
      expect(evaluateCondition(cond("truthy", "a"), { a: value })).toBe(false);
    }
    for (const value of [1, true, ["x"], "x"]) {
      expect(evaluateCondition(cond("truthy", "a"), { a: value })).toBe(true);
    }
  });

  it("compares eq/neq by plain equality", () => {
    expect(evaluateCondition(cond("eq", "a", "yes"), { a: "yes" })).toBe(true);
    expect(evaluateCondition(cond("eq", "a", "yes"), { a: "no" })).toBe(false);
    expect(evaluateCondition(cond("neq", "a", "yes"), { a: "no" })).toBe(true);
    expect(evaluateCondition(cond("neq", "a", "yes"), { a: "yes" })).toBe(false);
    expect(evaluateCondition(cond("eq", "a", true), { a: true })).toBe(true);
    expect(evaluateCondition(cond("eq", "a", 3), { a: 3 })).toBe(true);
  });

  it("reads `in` as membership for a scalar answer", () => {
    expect(evaluateCondition(cond("in", "a", ["x", "y"]), { a: "x" })).toBe(true);
    expect(evaluateCondition(cond("in", "a", ["x", "y"]), { a: "z" })).toBe(false);
    // A non-list `value` is a one-element list, exactly like the server.
    expect(evaluateCondition(cond("in", "a", "x"), { a: "x" })).toBe(true);
  });

  it("reads `in` as intersection for a list answer", () => {
    expect(evaluateCondition(cond("in", "a", ["x", "y"]), { a: ["y", "q"] })).toBe(true);
    expect(evaluateCondition(cond("in", "a", ["x", "y"]), { a: ["q"] })).toBe(false);
    expect(evaluateCondition(cond("in", "a", ["x"]), { a: [] })).toBe(false);
  });
});

describe("visibleFields", () => {
  const schema: FormSchema = {
    schema_version: 1,
    sections: [
      { key: "one", fields: [field("streams"), field("url", cond("truthy", "streams"))] },
      { key: "two", fields: [field("platform", cond("eq", "streams", true)), field("always")] },
    ],
  };

  it("keeps unconditional fields and drops the ones whose condition fails", () => {
    expect(visibleFields(schema, {}).map((f) => f.key)).toEqual(["streams", "always"]);
  });

  it("reveals conditional fields across sections, in schema order", () => {
    expect(visibleFields(schema, { streams: true }).map((f) => f.key)).toEqual([
      "streams",
      "url",
      "platform",
      "always",
    ]);
  });
});
