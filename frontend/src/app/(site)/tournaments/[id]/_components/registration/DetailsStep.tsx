"use client";

import { useEffect } from "react";
import type { RegistrationForm } from "@/types/registration.types";
import { cn } from "@/lib/utils";
import { Switch } from "@/components/ui/switch";
import { useTranslation } from "@/i18n/LanguageContext";
import CustomField from "./CustomField";
import FieldLabel from "./FieldLabel";
import { getBuiltInFieldValidationError } from "./validation";

interface DetailsStepProps {
  values: Record<string, string>;
  onUpdate: (key: string, value: string) => void;
  onFieldValidationChange: (fieldKey: string, error: string | null) => void;
  form: RegistrationForm;
}

export default function DetailsStep({
  values,
  onUpdate,
  onFieldValidationChange,
  form,
}: DetailsStepProps) {
  const { t } = useTranslation();
  const fields = form.built_in_fields;
  const showNotes = fields?.notes?.enabled !== false;
  const showStreamPov = fields?.stream_pov?.enabled === true;
  const notesValidationError = showNotes ? getBuiltInFieldValidationError(
    "notes",
    values.notes ?? "",
    fields?.notes,
    t,
  ) : null;

  useEffect(() => {
    onFieldValidationChange("notes", notesValidationError);
  }, [notesValidationError, onFieldValidationChange]);

  const hasCustomFields = form.custom_fields.length > 0;
  const hasAnyField = showNotes || showStreamPov || hasCustomFields;

  return (
    <div className="grid gap-4">
      <div className="space-y-1">
        <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-white/55">
          {t("registration.details.title")}
        </h3>
        <p className="text-xs leading-5 text-white/42">
          {hasAnyField
            ? t("registration.details.descWithFields")
            : t("registration.details.descNoFields")}
        </p>
      </div>

      {showStreamPov && (
        <div className="space-y-2">
          <FieldLabel
            label={t("registration.details.streamPov")}
            required={fields?.stream_pov?.required === true}
          />
          <label className="flex items-center gap-3">
            <Switch
              checked={values.stream_pov === "true"}
              onCheckedChange={(checked) => onUpdate("stream_pov", checked ? "true" : "false")}
            />
            <span className="text-sm text-white/70">{t("registration.details.streamPovLabel")}</span>
          </label>
        </div>
      )}

      {showNotes && (
        <div className="space-y-1.5">
          <FieldLabel
            label={t("registration.details.notes")}
            required={fields?.notes?.required === true}
          />
          <textarea
            placeholder={t("registration.details.notesPlaceholder")}
            value={values.notes ?? ""}
            onChange={(e) => onUpdate("notes", e.target.value)}
            rows={2}
            className={cn(
              "w-full rounded-lg border border-white/10 bg-white/3 px-3 py-2 text-sm text-white placeholder-white/30 outline-none transition-colors focus:border-white/20",
              notesValidationError && "border-red-500/70 text-red-100 placeholder:text-red-200/60 focus:border-red-500/70",
            )}
          />
          {notesValidationError && (
            <p className="text-xs text-red-400">{notesValidationError}</p>
          )}
        </div>
      )}

      {form.custom_fields.map((field) => (
        <CustomField
          key={field.key}
          definition={field}
          value={values[field.key] ?? ""}
          onChange={(v) => onUpdate(field.key, v)}
          onValidationChange={(error) => onFieldValidationChange(field.key, error)}
        />
      ))}
    </div>
  );
}

