"use client";

import { useFormatter, useTranslations } from "next-intl";

import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import type { QuotaDimension, QuotaScopeUsage } from "@/types/auth.types";
import { QUOTA_DIMENSIONS } from "@/types/auth.types";
import type { QuotaLimitsDraft } from "./dimensions";

export interface QuotaLimitFieldsProps {
  /** Field id prefix, so several of these can share one screen. */
  idPrefix: string;
  values: QuotaLimitsDraft;
  onChange: (dimension: QuotaDimension, value: number | null) => void;
  /** The scope's resolved limits, shown as "in force now" under each field. */
  effective?: QuotaScopeUsage | null;
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
 */
export function QuotaLimitFields({
  idPrefix,
  values,
  onChange,
  effective = null,
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
        const error = errors?.[dimension];
        const inForce = effective?.[dimension] ?? null;

        return (
          <div key={dimension} className="space-y-1.5">
            <Label htmlFor={fieldId}>{t(`dimensions.${dimension}.label`)}</Label>
            <NumberInput
              id={fieldId}
              integer
              min={0}
              value={values[dimension]}
              onValueChange={(next) => onChange(dimension, next)}
              placeholder={t("inheritPlaceholder")}
              disabled={disabled}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? `${errorId} ${hintId}` : hintId}
            />
            {error ? (
              <p id={errorId} className="text-xs font-medium text-danger">
                {error}
              </p>
            ) : null}
            <p id={hintId} className="text-xs text-muted-foreground">
              {t(`dimensions.${dimension}.hint`)}{" "}
              {effective
                ? t("effectiveNow", {
                    value: inForce === null ? t("unlimited") : format.number(inForce)
                  })
                : null}
            </p>
          </div>
        );
      })}
    </div>
  );
}
