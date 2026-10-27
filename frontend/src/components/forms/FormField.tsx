"use client";

import { useId, type KeyboardEventHandler, type ReactNode } from "react";

import { Input } from "@/components/ui/input";
import { NumberInput } from "@/components/ui/number-input";
import { Textarea } from "@/components/ui/textarea";

import FieldShell from "./FieldShell";

interface FormFieldProps {
  label: string;
  /** Stable control id. Generated when omitted so the label always associates. */
  id?: string;
  required?: boolean;
  icon?: ReactNode;
  /** Help line under the control, wired via `aria-describedby`. */
  help?: ReactNode;
  /** Validation message. Rendered in a `<p>` wired via `aria-describedby`. */
  error?: string | null;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: "text" | "number" | "url";
  /** Render a `<textarea>` instead of an `<input>`. */
  multiline?: boolean;
  /** Read-only: the answer is shown, not asked for. */
  disabled?: boolean;
  onKeyDown?: KeyboardEventHandler<HTMLInputElement | HTMLTextAreaElement>;
  /** Content between the label and the control (e.g. a tag list). */
  beforeControl?: ReactNode;
  /** Absolutely-positioned content inside the control's right edge. */
  endAdornment?: ReactNode;
  /** Extra classes on the control itself. */
  className?: string;
  /** Extra classes on the label/control/error wrapper. */
  containerClassName?: string;
}

/** A text, number or URL answer (or a multi-line one) on the public control surface. */
export default function FormField({
  label,
  id: providedId,
  required = false,
  icon,
  help,
  error = null,
  value,
  onChange,
  placeholder,
  type = "text",
  multiline = false,
  disabled = false,
  onKeyDown,
  beforeControl,
  endAdornment,
  className,
  containerClassName
}: Readonly<FormFieldProps>) {
  const generatedId = useId();
  const id = providedId ?? generatedId;

  // The value stays a STRING across this component's API — every caller keeps a
  // string answer — so the numeric control gets a parsed view of it. A stored
  // non-number renders empty rather than as `NaN`; the server refuses one
  // anyway (`_coerce_number`).
  const parsed = Number(value);
  const numericValue = value !== "" && Number.isFinite(parsed) ? parsed : null;

  return (
    <FieldShell
      id={id}
      label={label}
      required={required}
      icon={icon}
      help={help}
      error={error}
      className={containerClassName}
    >
      {(aria) => {
        const shared = {
          ...aria,
          placeholder,
          onKeyDown,
          disabled,
          className
        };
        const control = multiline ? (
          <Textarea {...shared} value={value} onChange={(event) => onChange(event.target.value)} />
        ) : type === "number" ? (
          // The library's text-based numeric input: the native spinner's arrows are
          // an unreadable 10px stub in this theme, and its wheel/arrow-key stepping
          // silently edits an answer the user only meant to scroll past.
          <NumberInput
            {...shared}
            value={numericValue}
            onValueChange={(next) => onChange(next === null ? "" : String(next))}
          />
        ) : (
          <Input
            {...shared}
            type={type}
            value={value}
            onChange={(event) => onChange(event.target.value)}
          />
        );
        return (
          <>
            {beforeControl}
            {endAdornment ? (
              <div className="relative">
                {control}
                {endAdornment}
              </div>
            ) : (
              control
            )}
          </>
        );
      }}
    </FieldShell>
  );
}
