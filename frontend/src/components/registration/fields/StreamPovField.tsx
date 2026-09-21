"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import type { FieldRendererProps } from "@/components/forms/types";
import { Switch } from "@/components/ui/switch";

import FieldLabel from "../FieldLabel";

/** The `stream_pov` builtin: "I can provide a point-of-view stream". */
export default function StreamPovField({
  field,
  value,
  onChange,
  error,
}: Readonly<FieldRendererProps>) {
  const t = useTranslations();
  const id = useId();
  const errorId = `${id}-error`;

  return (
    <div className="space-y-2">
      <FieldLabel
        label={field.label || t("registration.details.streamPov")}
        htmlFor={id}
        required={field.required}
      />
      {/* Radix Switch renders a <button>; a wrapping <label> would not
          associate it, so the id/htmlFor pair carries the name. */}
      <div className="flex items-center gap-3">
        <Switch
          id={id}
          checked={value === true || value === "true"}
          onCheckedChange={onChange}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? errorId : undefined}
        />
        <span className="text-sm text-[color:var(--aqt-fg-muted)]">
          {field.help || t("registration.details.streamPovLabel")}
        </span>
      </div>
      {error ? (
        <p id={errorId} className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
