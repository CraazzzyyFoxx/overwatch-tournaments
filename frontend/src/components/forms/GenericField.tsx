"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

import FieldShell from "./FieldShell";
import FormField from "./FormField";
import type { FieldRendererProps } from "./types";

/**
 * The boolean builtins, answered by the `checkbox` case, and the wording each
 * falls back to when the organizer left the label and the help empty.
 *
 * Full message paths as LITERALS: the translator is typed against the message
 * tree, so a widened `string` key would not resolve.
 */
const BOOLEAN_BUILTIN_COPY = {
  stream_pov: {
    label: "registration.details.streamPov",
    help: "registration.details.streamPovLabel",
  },
  reserve: {
    label: "registration.details.reserve",
    help: "registration.details.reserveLabel",
  },
} as const;

/**
 * Every question without a renderer of its own, from one `switch` on its kind.
 *
 * One component rather than eight files: the kinds differ only in their control
 * element, and the label/help/error/`aria-describedby` wiring around it is
 * `FieldShell`'s.
 */
export default function GenericField({
  field,
  value,
  onChange,
  error,
  disabled = false,
}: Readonly<FieldRendererProps>) {
  const t = useTranslations();
  const id = useId();
  // `stream_pov` ("I can provide a POV stream") and `reserve` ("you can call me
  // in if somebody drops"): builtins whose answer is a plain boolean.
  const fallback =
    field.key === "stream_pov" || field.key === "reserve" ? BOOLEAN_BUILTIN_COPY[field.key] : null;
  const label = field.label || (fallback ? t(fallback.label) : field.key);
  const help = field.help || (fallback ? t(fallback.help) : null);
  const options = field.options ?? [];
  const shell = { id, label, required: field.required, help, error };

  switch (fallback ? "checkbox" : field.kind) {
    case "checkbox":
      return (
        <FieldShell {...shell} layout="inline">
          {(control) => (
            <Switch
              {...control}
              checked={value === true || value === "true"}
              onCheckedChange={onChange}
              disabled={disabled}
            />
          )}
        </FieldShell>
      );

    case "select":
      return (
        <FieldShell {...shell}>
          {(control) => (
            // Radix Select rejects an empty item value, so the empty state is
            // the trigger placeholder rather than a blank option.
            <Select
              value={typeof value === "string" && value ? value : undefined}
              onValueChange={onChange}
              disabled={disabled}
            >
              <SelectTrigger {...control} variant="surface">
                <SelectValue placeholder={field.placeholder || t("common.selectPlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {options.map((option) => (
                  <SelectItem key={option} value={option}>
                    {option}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </FieldShell>
      );

    case "multi_select": {
      const selected = Array.isArray(value) ? (value as unknown[]).map(String) : [];
      return (
        <FieldShell {...shell} layout="group">
          {(control) => (
            <div className="grid gap-1.5">
              {options.map((option) => (
                <label
                  key={option}
                  className="inline-flex items-center gap-2 text-sm text-[color:var(--aqt-fg-muted)]"
                >
                  <Checkbox
                    aria-invalid={control["aria-invalid"]}
                    checked={selected.includes(option)}
                    disabled={disabled}
                    onCheckedChange={(checked) =>
                      onChange(
                        checked === true
                          ? [...selected, option]
                          : selected.filter((item) => item !== option),
                      )
                    }
                  />
                  {option}
                </label>
              ))}
            </div>
          )}
        </FieldShell>
      );
    }

    case "date":
      return (
        <FieldShell {...shell}>
          {(control) => (
            // The platform's own picker: a date library here would ship a
            // calendar widget to replace a control every browser already has.
            <Input
              {...control}
              type="date"
              value={typeof value === "string" ? value : ""}
              onChange={(event) => onChange(event.target.value)}
              disabled={disabled}
            />
          )}
        </FieldShell>
      );

    default:
      // `text`, `textarea`, `number`, `url` — and anything a newer server adds,
      // which is still answerable as free text rather than not rendered at all.
      return (
        <FormField
          id={id}
          label={label}
          required={field.required}
          help={help}
          multiline={field.kind === "textarea"}
          type={field.kind === "number" ? "number" : field.kind === "url" ? "url" : "text"}
          placeholder={field.placeholder ?? ""}
          value={typeof value === "string" || typeof value === "number" ? String(value) : ""}
          onChange={onChange}
          disabled={disabled}
          error={error}
        />
      );
  }
}
