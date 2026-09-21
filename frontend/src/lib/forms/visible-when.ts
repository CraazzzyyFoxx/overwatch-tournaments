/**
 * `visible_when` evaluation, a verbatim mirror of
 * `backend/shared/domain/forms/validate.py::evaluate_condition`.
 *
 * The two MUST agree: the client decides what to render and what to send, the
 * server decides what is required and what it stores. A field the client hides
 * but the server considers visible is a submission blocked on a question nobody
 * was asked.
 */

import type { Answers, Condition, FormField, FormSchema } from "@/types/forms.types";

/** A checkbox that round-tripped through a form encoding arrives as the string
 *  `"false"`, which is not a truthy answer. */
const FALSE_STRINGS: Record<string, true> = { "": true, false: true, "0": true };

function truthy(value: unknown): boolean {
  if (typeof value === "string") return FALSE_STRINGS[value.trim().toLowerCase()] !== true;
  // `bool([])` is False in Python and `Boolean([])` is true in JS: an empty
  // multi-select answer must not reveal a field the server considers hidden.
  if (Array.isArray(value)) return value.length > 0;
  return Boolean(value);
}

/** Whether `condition` holds for `answers`. A missing answer is falsy, never an error. */
export function evaluateCondition(condition: Condition, answers: Answers): boolean {
  const answer = answers[condition.field];
  if (condition.op === "truthy") return truthy(answer);
  if (condition.op === "in") {
    const options = Array.isArray(condition.value) ? condition.value : [condition.value];
    if (Array.isArray(answer)) return answer.some((item) => options.includes(item));
    return options.includes(answer);
  }
  if (condition.op === "neq") return answer !== condition.value;
  return answer === condition.value;
}

/** Every field of `schema`, in section order, that `answers` is asked for. */
export function visibleFields(schema: FormSchema, answers: Answers): FormField[] {
  return schema.sections.flatMap((section) =>
    section.fields.filter(
      (field) => !field.visible_when || evaluateCondition(field.visible_when, answers),
    ),
  );
}
