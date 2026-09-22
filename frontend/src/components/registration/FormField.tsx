"use client";

import { useId, type KeyboardEventHandler, type ReactNode } from "react";

import { Input } from "@/components/ui/input";
import { NumberInput } from "@/components/ui/number-input";
import { cn } from "@/lib/utils";
import FieldLabel from "./FieldLabel";

/**
 * Shared control surface for every registration control.
 *
 * Each of the six former copies of this class string paired `outline-none` with
 * a `focus:border-…` swap to the exact token the border already carried — a
 * no-op — so keyboard focus was invisible across the whole public registration
 * flow. The replacement is a real `focus-visible:` ring.
 */
export const fieldControlClass =
  "w-full rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] px-3 text-base sm:text-sm " +
  "text-[color:var(--aqt-fg)] shadow-none placeholder:text-[color:var(--aqt-fg-dim)] transition-colors " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 " +
  "focus-visible:ring-offset-background";

/** Error styling for any control built on `fieldControlClass`. */
export const fieldInvalidClass =
  "border-destructive text-destructive placeholder:text-destructive/60";

interface FormFieldProps {
  label: string;
  /** Stable control id. Generated when omitted so the label always associates. */
  id?: string;
  required?: boolean;
  icon?: ReactNode;
  /** Validation message. Rendered in a `<p>` wired via `aria-describedby`. */
  error?: string | null;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: "text" | "number" | "url";
  /** Render a `<textarea>` instead of an `<input>`. */
  multiline?: boolean;
  rows?: number;
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

export default function FormField({
  label,
  id: providedId,
  required = false,
  icon,
  error = null,
  value,
  onChange,
  placeholder,
  type = "text",
  multiline = false,
  disabled = false,
  rows = 2,
  onKeyDown,
  beforeControl,
  endAdornment,
  className,
  containerClassName,
}: Readonly<FormFieldProps>) {
  const generatedId = useId();
  const id = providedId ?? generatedId;
  const errorId = `${id}-error`;
  const invalid = Boolean(error);

  const controlClass = cn(fieldControlClass, invalid && fieldInvalidClass, className);

  // The value stays a STRING across this component's API — every caller keeps a
  // string answer — so the numeric control gets a parsed view of it. A stored
  // non-number renders empty rather than as `NaN`; the server refuses one
  // anyway (`_coerce_number`).
  const parsed = Number(value);
  const numericValue = value !== "" && Number.isFinite(parsed) ? parsed : null;

  const control = multiline ? (
    <textarea
      id={id}
      rows={rows}
      placeholder={placeholder}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      onKeyDown={onKeyDown}
      disabled={disabled}
      aria-invalid={invalid}
      aria-describedby={invalid ? errorId : undefined}
      className={cn(controlClass, "py-2")}
    />
  ) : type === "number" ? (
    // The library's text-based numeric input: the native spinner's arrows are
    // an unreadable 10px stub in this theme, and its wheel/arrow-key stepping
    // silently edits an answer the user only meant to scroll past.
    <NumberInput
      id={id}
      placeholder={placeholder}
      value={numericValue}
      onValueChange={(next) => onChange(next === null ? "" : String(next))}
      onKeyDown={onKeyDown}
      disabled={disabled}
      aria-invalid={invalid}
      aria-describedby={invalid ? errorId : undefined}
      className={cn(controlClass, "h-9")}
    />
  ) : (
    <Input
      id={id}
      type={type}
      placeholder={placeholder}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      onKeyDown={onKeyDown}
      disabled={disabled}
      aria-invalid={invalid}
      aria-describedby={invalid ? errorId : undefined}
      className={cn(controlClass, "h-9")}
    />
  );

  return (
    <div className={cn("space-y-2", containerClassName)}>
      <FieldLabel label={label} htmlFor={id} required={required} icon={icon} />
      {beforeControl}
      {endAdornment ? (
        <div className="relative">
          {control}
          {endAdornment}
        </div>
      ) : (
        control
      )}
      {error ? (
        <p id={errorId} className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
