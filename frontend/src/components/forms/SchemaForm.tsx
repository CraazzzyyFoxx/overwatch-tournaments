"use client";

import { useEffect, type ReactNode } from "react";

import StepIndicator from "@/components/registration/StepIndicator";
import { validateAnswer } from "@/lib/forms/validate";
import { evaluateCondition } from "@/lib/forms/visible-when";
import type { Answers, FormField, FormSchema, FormSection } from "@/types/forms.types";

import GenericField from "./GenericField";
import type { FieldRendererContext, RendererRegistry } from "./types";

/** Whether `answers` is asked for this field right now. */
function isVisible(field: FormField, answers: Answers): boolean {
  return !field.visible_when || evaluateCondition(field.visible_when, answers);
}

/**
 * The sections that are actually a step: those with at least one VISIBLE field.
 *
 * The step list used to be a hard-coded three, so a tournament with no notes,
 * no stream POV and no custom fields still made the registrant click through a
 * "Details" step whose entire content was "No additional fields required". The
 * fallback to the first section keeps a schema whose every field is currently
 * hidden from rendering as a form with no steps at all.
 */
export function schemaSteps(schema: FormSchema, answers: Answers): FormSection[] {
  const withContent = schema.sections.filter((section) =>
    section.fields.some((field) => isVisible(field, answers)),
  );
  return withContent.length > 0 ? withContent : schema.sections.slice(0, 1);
}

export interface SchemaFormFooterState {
  canGoBack: boolean;
  isLast: boolean;
  /** First client-side objection on this step, whether or not it is shown yet. */
  stepError: string | null;
}

export interface SchemaFormProps {
  schema: FormSchema;
  answers: Answers;
  onChange: (key: string, value: unknown) => void;
  renderers: RendererRegistry;
  context: FieldRendererContext;
  /** Server rejections keyed by answer key. Always shown — the server saw them. */
  serverErrors: Record<string, string>;
  step: number;
  onStepChange: (index: number) => void;
  /** Reveal client-side objections. Off until the registrant tries to advance. */
  showErrors: boolean;
  readOnly?: boolean;
  footer: (state: SchemaFormFooterState) => ReactNode;
}

/**
 * A `FormSchema` rendered as a wizard, one section per step.
 *
 * Holds no answer state: the parent owns `answers`, because the submit payload,
 * the prefill and the admin editor's non-schema panel all live there and a
 * second copy inside here would have to be pushed back out on every keystroke.
 *
 * Client-side validation is the GENERIC rules only (`validateAnswer`). Role
 * composition, verified accounts and every other builtin rule are the server's:
 * they need server state, and a second copy of a rule is a rule that drifts.
 */
export default function SchemaForm({
  schema,
  answers,
  onChange,
  renderers,
  context,
  serverErrors,
  step,
  onStepChange,
  showErrors,
  readOnly = false,
  footer,
}: Readonly<SchemaFormProps>) {
  const steps = schemaSteps(schema, answers);
  const index = Math.min(Math.max(step, 0), Math.max(steps.length - 1, 0));
  const section = steps[index] as FormSection | undefined;
  const fields = section?.fields.filter((field) => isVisible(field, answers)) ?? [];

  // Answering a `visible_when` controller can empty the step the registrant is
  // standing on. Clamping alone would leave the parent's index out of range,
  // so the correction is pushed back up rather than silently diverging.
  useEffect(() => {
    if (step !== index) onStepChange(index);
  }, [step, index, onStepChange]);

  let stepError: string | null = null;
  for (const field of fields) {
    const objection = validateAnswer(field, answers[field.key], context.t);
    if (objection) {
      stepError = objection;
      break;
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {steps.length > 1 && (
        <StepIndicator
          steps={steps.map((entry) => ({ label: entry.title || entry.key }))}
          current={index}
        />
      )}

      {/* A disabled fieldset disables every control inside it, which is the
          whole of read-only mode — the builder's preview tab needs nothing more. */}
      <fieldset disabled={readOnly} className="m-0 grid min-w-0 gap-4 border-0 p-0">
        {section?.description ? (
          <p className="text-xs leading-5 text-[color:var(--aqt-fg-muted)]">
            {section.description}
          </p>
        ) : null}

        {fields.map((field) => {
          const Renderer = renderers[field.key] ?? renderers[field.kind] ?? GenericField;
          const error =
            serverErrors[field.key] ??
            (showErrors ? validateAnswer(field, answers[field.key], context.t) : null);
          return (
            <Renderer
              key={field.key}
              field={field}
              value={answers[field.key]}
              onChange={(value) => onChange(field.key, value)}
              error={error}
              context={context}
            />
          );
        })}
      </fieldset>

      {footer({ canGoBack: index > 0, isLast: index >= steps.length - 1, stepError })}
    </div>
  );
}
