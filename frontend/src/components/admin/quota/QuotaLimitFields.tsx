"use client";

import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import type { QuotaDimension, QuotaLimitsPayload } from "@/types/auth.types";
import { QUOTA_DIMENSIONS } from "@/types/auth.types";
import type { QuotaLimitsDraft } from "./dimensions";

export interface QuotaLimitFieldsProps {
  /** Field id prefix, so several of these can share one screen. */
  idPrefix: string;
  values: QuotaLimitsDraft;
  onChange: (dimension: QuotaDimension, value: number | null) => void;
  /** The ceiling an empty field inherits, and the bar a write must stay under. */
  inherited?: QuotaLimitsPayload | null;
  /** Dimensions the draft raises above `inherited`. */
  raised?: readonly QuotaDimension[];
  /** Whether this operator may store a raise at all (superuser). */
  canRaise?: boolean;
  /** Per-dimension rejection text, rendered under the input it belongs to. */
  errors?: Partial<Record<QuotaDimension, string>>;
  disabled?: boolean;
}

/**
 * The five quota dimensions as editable numbers.
 *
 * An empty field is `null` — *inherit* from the scope above, never zero: zero
 * is a real, stored value that blocks the operation outright, and conflating
 * the two would turn "stop overriding this" into an outage.
 *
 * A value above the inherited ceiling is the one edit authority splits on, so
 * it is marked in place rather than left to a 422: refused outright for an
 * admin, flagged as a superuser override for the account that may store it.
 */
export function QuotaLimitFields({
  idPrefix,
  values,
  onChange,
  inherited = null,
  raised = [],
  canRaise = false,
  errors,
  disabled = false
}: Readonly<QuotaLimitFieldsProps>) {
  const t = useTranslations("quota");
  const format = useFormatter();

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {QUOTA_DIMENSIONS.map((dimension) => {
        const fieldId = `${idPrefix}-${dimension}`;
        const hintId = `${fieldId}-hint`;
        const errorId = `${fieldId}-error`;
        const noteId = `${fieldId}-raise`;
        const label = t(`dimensions.${dimension}.label`);
        const ceiling = inherited?.[dimension] ?? null;
        const isRaise = raised.includes(dimension);
        // A raise this operator may not store is a rejection, not a remark:
        // the server would answer 422, so the field says so before the round
        // trip — in the same words the server would have used.
        const refused =
          isRaise && !canRaise
            ? ceiling === null
              ? t("errors.aboveInheritedUnlimited", { dimension: label })
              : t("errors.aboveInherited", {
                  dimension: label,
                  limit: ceiling,
                  requested: values[dimension] ?? 0
                })
            : undefined;
        const error = errors?.[dimension] ?? refused;
        const described = [error ? errorId : null, isRaise && canRaise ? noteId : null, hintId]
          .filter(Boolean)
          .join(" ");

        return (
          <div key={dimension} className="space-y-1.5">
            <div className="flex min-h-6 items-center justify-between gap-2">
              <Label htmlFor={fieldId}>{label}</Label>
              {isRaise ? (
                <Badge tone={canRaise ? "warning" : "danger"} className="font-normal">
                  {t("superuserOnly")}
                </Badge>
              ) : null}
            </div>
            <NumberInput
              id={fieldId}
              integer
              min={0}
              value={values[dimension]}
              onValueChange={(next) => onChange(dimension, next)}
              placeholder={
                ceiling === null
                  ? t("inheritPlaceholder")
                  : t("inheritPlaceholderValue", { value: format.number(ceiling) })
              }
              disabled={disabled}
              aria-invalid={error ? true : undefined}
              aria-describedby={described}
            />
            {error ? (
              <p id={errorId} className="text-xs font-medium text-danger">
                {error}
              </p>
            ) : null}
            {isRaise && canRaise ? (
              <p id={noteId} className="text-xs font-medium text-warning">
                {ceiling === null
                  ? t("raiseAboveUnlimited")
                  : t("raiseAbove", { limit: format.number(ceiling) })}
              </p>
            ) : null}
            <p id={hintId} className="text-xs text-muted-foreground">
              {t(`dimensions.${dimension}.hint`)}{" "}
              {inherited
                ? t("inheritedCeiling", {
                    value: ceiling === null ? t("unlimited") : format.number(ceiling)
                  })
                : null}
            </p>
          </div>
        );
      })}
    </div>
  );
}
