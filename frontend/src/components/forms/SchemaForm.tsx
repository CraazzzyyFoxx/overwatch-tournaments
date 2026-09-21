"use client";

import { useEffect, type ReactNode } from "react";
import { EyeOff, Lock } from "lucide-react";
import { useTranslations } from "next-intl";

import StepIndicator from "@/components/registration/StepIndicator";
import { declaredRoles } from "@/lib/forms/answers";
import { validateAnswer } from "@/lib/forms/validate";
import { evaluateCondition } from "@/lib/forms/visible-when";
import type { Answers, FormField, FormSchema, FormSection } from "@/types/forms.types";

import GenericField from "./GenericField";
import type { FieldRendererContext, RendererRegistry } from "./types";

/** Whether `answers` is asked for this field right now. */
function isVisible(field: FormField, answers: Answers): boolean {
  return !field.visible_when || evaluateCondition(field.visible_when, answers);
}

/** The hint to render under a field the viewer may not change, keyed by answer
 *  key. A key's presence IS the lock; the value says why. */
export type LockedFields = Readonly<Record<string, string>>;

/**
 * The sections that are actually a step: those with at least one VISIBLE field.
 *
 * The step list used to be a hard-coded three, so a tournament with no notes,
 * no stream POV and no custom fields still made the registrant click through a
 * "Details" step whose entire content was "No additional fields required". The
 * fallback to the first section keeps a schema whose every field is currently
 * hidden from rendering as a form with no steps at all.
 *
 * `isActionable` is the edit case: a step whose every visible field is
 * read-only has nothing on it to do, so it is dropped rather than shown as a
 * page of greyed-out controls to click Next through. Absent = every visible
 * field counts, which is every other caller.
 */
export function schemaSteps(
  schema: FormSchema,
  answers: Answers,
  isActionable?: (field: FormField) => boolean,
): FormSection[] {
  const withContent = schema.sections.filter((section) =>
    section.fields.some(
      (field) => isVisible(field, answers) && (!isActionable || isActionable(field)),
    ),
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
  /**
   * Fields this viewer may read but not write, each mapped to the hint that
   * says why. Rendered disabled AND wrapped in a disabled `<fieldset>`, so the
   * lock holds whether or not the field's renderer honours `disabled`.
   */
  lockedFields?: LockedFields;
  /**
   * Drop a step whose every visible field is locked. On by the edit path only:
   * a first submission locks single answers (a forced `reserve`) on steps that
   * still have work on them.
   */
  skipLockedSteps?: boolean;
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
  lockedFields,
  skipLockedSteps = false,
  footer,
}: Readonly<SchemaFormProps>) {
  const t = useTranslations("forms");
  const steps = schemaSteps(
    schema,
    answers,
    skipLockedSteps ? (field) => lockedFields?.[field.key] === undefined : undefined,
  );
  const index = Math.min(Math.max(step, 0), Math.max(steps.length - 1, 0));
  const section = steps[index] as FormSection | undefined;
  const fields = section?.fields.filter((field) => isVisible(field, answers)) ?? [];

  // Answering a `visible_when` controller can empty the step the registrant is
  // standing on. Clamping alone would leave the parent's index out of range,
  // so the correction is pushed back up rather than silently diverging.
  useEffect(() => {
    if (step !== index) onStepChange(index);
  }, [step, index, onStepChange]);

  /**
   * The client's objection to one answer, or `null`.
   *
   * `required` is a rule for the REGISTRANT. An organizer enters what they
   * know — the server runs the organizer write paths with
   * `enforce_required=False` for exactly that reason — so a blank required
   * field must not lock them out of an unrelated fix on a row that predates
   * the question. Asking `validateAnswer` about a not-required copy of the
   * field drops that one rule and keeps every other: a malformed BattleTag is
   * still malformed when an organizer types it.
   */
  const objectionTo = (field: FormField): string | null => {
    const rule = context.mode === "admin" && field.required ? { ...field, required: false } : field;
    return validateAnswer(rule, answers[field.key], context.t, answers);
  };

  let stepError: string | null = null;
  for (const field of fields) {
    // A locked field's objection is not this viewer's to clear, so it must not
    // hold the step: an edit that may only touch `public_notes` would be stuck
    // behind a required question it is forbidden to answer.
    if (lockedFields?.[field.key] !== undefined) continue;
    const objection = objectionTo(field);
    if (objection) {
      stepError = objection;
      break;
    }
  }

  // Derived here rather than by each host: a renderer that needs to know which
  // roles the registration declares (the per-role rank block marks exactly
  // those required) reads it off the same document this form already owns.
  const fieldContext: FieldRendererContext = {
    ...context,
    declaredRoles: declaredRoles(answers),
  };

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
          const lockHint = lockedFields?.[field.key];
          // A server rejection still shows on a locked field — it names THIS
          // write ("locked") — but a client-side objection does not: telling
          // somebody an answer is required under a control they cannot reach is
          // advice with no action.
          const error =
            serverErrors[field.key] ??
            (showErrors && lockHint === undefined ? objectionTo(field) : null);
          const control = (
            <Renderer
              field={field}
              value={answers[field.key]}
              onChange={(value) => onChange(field.key, value)}
              error={error}
              disabled={lockHint !== undefined}
              context={fieldContext}
            />
          );
          // The registrant answers organizers-only questions like any other —
          // `visibility` is about who READS the answer. Saying so is the whole
          // difference they can perceive, so it is said once, here, rather than
          // in each of the eight renderers.
          const organizersOnly =
            field.visibility === "organizers" && context.mode !== "admin";
          if (lockHint === undefined && !organizersOnly) {
            return <div key={field.key}>{control}</div>;
          }
          return (
            <div key={field.key} className="grid gap-1.5">
              {/* The lock ENFORCED, not merely styled: a disabled fieldset
                  disables every control inside it, so a renderer that ignores
                  `disabled` is still read-only. */}
              {lockHint === undefined ? (
                control
              ) : (
                <fieldset disabled className="m-0 min-w-0 border-0 p-0 opacity-60">
                  {control}
                </fieldset>
              )}
              {lockHint === undefined ? null : (
                <p className="inline-flex items-center gap-1.5 text-label text-[color:var(--aqt-fg-dim)]">
                  <Lock className="size-3 shrink-0" aria-hidden />
                  {lockHint}
                </p>
              )}
              {organizersOnly ? (
                <p className="inline-flex items-center gap-1.5 text-label text-[color:var(--aqt-fg-dim)]">
                  <EyeOff className="size-3 shrink-0" aria-hidden />
                  {t("organizersOnly")}
                </p>
              ) : null}
            </div>
          );
        })}
      </fieldset>

      {footer({ canGoBack: index > 0, isLast: index >= steps.length - 1, stepError })}
    </div>
  );
}
