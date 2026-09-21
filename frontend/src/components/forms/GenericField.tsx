"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import FieldLabel from "@/components/registration/FieldLabel";
import FormField, {
  fieldControlClass,
  fieldInvalidClass,
} from "@/components/registration/FormField";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

import type { FieldRendererProps } from "./types";

/**
 * Every non-builtin question, from one `switch (field.kind)`.
 *
 * One component rather than eight files: the kinds differ only in their control
 * element, and the label/error/`aria-describedby` wiring around it — the part
 * that was wrong in six separate copies before `FormField` existed — is
 * identical for all of them.
 */
export default function GenericField({
  field,
  value,
  onChange,
  error,
}: Readonly<FieldRendererProps>) {
  const t = useTranslations();
  const id = useId();
  const errorId = `${id}-error`;
  const label = field.label || field.key;
  const options = field.options ?? [];

  const errorNode = error ? (
    <p id={errorId} className="text-xs text-destructive">
      {error}
    </p>
  ) : null;

  const helpNode = field.help ? (
    <p className="text-xs leading-5 text-[color:var(--aqt-fg-muted)]">{field.help}</p>
  ) : null;

  switch (field.kind) {
    case "checkbox":
      return (
        <div className="space-y-2">
          {/* Radix Switch renders a <button>, so a wrapping <label> would not
              associate it. The id/htmlFor pair does. */}
          <div className="flex items-center gap-3">
            <Switch
              id={id}
              checked={value === true || value === "true"}
              onCheckedChange={onChange}
              aria-invalid={Boolean(error)}
              aria-describedby={error ? errorId : undefined}
            />
            <FieldLabel label={label} htmlFor={id} required={field.required} />
          </div>
          {helpNode}
          {errorNode}
        </div>
      );

    case "select":
      return (
        <div className="space-y-2">
          <FieldLabel label={label} htmlFor={id} required={field.required} />
          {/* Radix Select rejects an empty item value, so the empty state is the
              trigger placeholder rather than a blank option. */}
          <Select
            value={typeof value === "string" && value ? value : undefined}
            onValueChange={onChange}
          >
            <SelectTrigger
              id={id}
              aria-invalid={Boolean(error)}
              aria-describedby={error ? errorId : undefined}
              className={cn(fieldControlClass, "h-9", error && fieldInvalidClass)}
            >
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
          {helpNode}
          {errorNode}
        </div>
      );

    case "multi_select": {
      const selected = Array.isArray(value) ? (value as unknown[]).map(String) : [];
      return (
        <fieldset
          className="m-0 min-w-0 space-y-2 border-0 p-0"
          aria-invalid={Boolean(error)}
          aria-describedby={error ? errorId : undefined}
        >
          <legend className="contents">
            <FieldLabel label={label} required={field.required} />
          </legend>
          <div className="grid gap-1.5">
            {options.map((option) => (
              <label
                key={option}
                className="inline-flex items-center gap-2 text-sm text-[color:var(--aqt-fg-muted)]"
              >
                <input
                  type="checkbox"
                  checked={selected.includes(option)}
                  onChange={(event) =>
                    onChange(
                      event.target.checked
                        ? [...selected, option]
                        : selected.filter((item) => item !== option),
                    )
                  }
                  className="size-4 rounded border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] accent-[color:var(--aqt-teal)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                />
                {option}
              </label>
            ))}
          </div>
          {helpNode}
          {errorNode}
        </fieldset>
      );
    }

    case "date":
      return (
        <div className="space-y-2">
          <FieldLabel label={label} htmlFor={id} required={field.required} />
          {/* The platform's own picker: a date library here would ship a
              calendar widget to replace a control every browser already has. */}
          <input
            id={id}
            type="date"
            value={typeof value === "string" ? value : ""}
            onChange={(event) => onChange(event.target.value)}
            aria-invalid={Boolean(error)}
            aria-describedby={error ? errorId : undefined}
            className={cn(fieldControlClass, "h-9", error && fieldInvalidClass)}
          />
          {helpNode}
          {errorNode}
        </div>
      );

    default:
      // `text`, `textarea`, `number`, `url` — and anything a newer server adds,
      // which is still answerable as free text rather than not rendered at all.
      return (
        <div className="space-y-1.5">
          <FormField
            id={id}
            label={label}
            required={field.required}
            multiline={field.kind === "textarea"}
            type={field.kind === "number" ? "number" : field.kind === "url" ? "url" : "text"}
            placeholder={field.placeholder ?? ""}
            value={typeof value === "string" || typeof value === "number" ? String(value) : ""}
            onChange={onChange}
            error={error}
          />
          {helpNode}
        </div>
      );
  }
}
