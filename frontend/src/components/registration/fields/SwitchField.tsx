"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import type { FieldRendererProps } from "@/components/forms/types";
import { Switch } from "@/components/ui/switch";

import FieldLabel from "../FieldLabel";

/**
 * The wording each boolean builtin falls back to when the organizer left the
 * label and the help empty — the only thing that ever differed between the
 * two switches, which is why they are one component.
 *
 * Full message paths as LITERALS: the translator is typed against the message
 * tree, so a widened `string` key would not resolve.
 */
const FALLBACK_COPY = {
  stream_pov: {
    label: "registration.details.streamPov",
    help: "registration.details.streamPovLabel"
  },
  reserve: {
    label: "registration.details.reserve",
    help: "registration.details.reserveLabel"
  }
} as const;

/** The boolean builtins: `stream_pov` ("I can provide a POV stream") and
 *  `reserve` ("call me in if a replacement is needed"). */
export default function SwitchField({
  field,
  value,
  onChange,
  error,
  disabled = false
}: Readonly<FieldRendererProps>) {
  const t = useTranslations();
  const id = useId();
  const errorId = `${id}-error`;

  const fallback = FALLBACK_COPY[field.key as keyof typeof FALLBACK_COPY] ?? null;

  return (
    <div className="space-y-2">
      <FieldLabel
        label={field.label || (fallback ? t(fallback.label) : field.key)}
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
          disabled={disabled}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? errorId : undefined}
        />
        <span className="text-sm text-[color:var(--aqt-fg-muted)]">
          {field.help || (fallback ? t(fallback.help) : "")}
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
