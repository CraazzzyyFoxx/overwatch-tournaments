"use client";

import type { ReactNode } from "react";

import { Field, FieldDescription, FieldError } from "@/components/ui/field";
import { cn } from "@/lib/utils";

import FieldLabel from "./FieldLabel";

/** Spread on the control a {@link FieldShell} labels: its id, and the error/help it is described by. */
interface FieldControlProps {
  id: string;
  "aria-invalid": boolean;
  "aria-describedby": string | undefined;
}

interface FieldShellProps {
  /** The control's id. The label points at it; the help and error ids derive from it. */
  id: string;
  label: string;
  required?: boolean;
  icon?: ReactNode;
  help?: ReactNode;
  /** Validation message, wired to the control through `aria-describedby`. */
  error?: string | null;
  /**
   * `stacked`: label over the control. `inline`: the control, then its label,
   * on one row (a switch). `group`: several controls under one name — a
   * `<fieldset>` whose `<legend>` is the label and which carries the
   * description; `aria-invalid` is not supported on a group, so it goes on the
   * controls themselves (a radio set: on its `radiogroup`) from the render prop.
   */
  layout?: "stacked" | "inline" | "group";
  className?: string;
  /** The control; as a function it receives the props to spread on it. */
  children: ReactNode | ((control: FieldControlProps) => ReactNode);
}

/**
 * Label, control, help and error of one form field — the `aria-describedby` /
 * `aria-invalid` / error-id wiring lives here once instead of in every field.
 */
export default function FieldShell({
  id,
  label,
  required = false,
  icon,
  help,
  error = null,
  layout = "stacked",
  className,
  children
}: Readonly<FieldShellProps>) {
  const helpId = help ? `${id}-help` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const control: FieldControlProps = {
    id,
    "aria-invalid": Boolean(error),
    // The error first: it is what the reader has to act on.
    "aria-describedby": [errorId, helpId].filter(Boolean).join(" ") || undefined
  };
  const body = typeof children === "function" ? children(control) : children;
  const labelNode = (
    <FieldLabel
      label={label}
      htmlFor={layout === "group" ? undefined : id}
      required={required}
      icon={icon}
    />
  );
  const messages = (
    <>
      {help ? (
        // `FieldDescription` tucks 4px closer when it is second-to-last, which
        // here only happens once an error follows it: the help would jump.
        <FieldDescription id={helpId} size="sm" className="nth-last-2:mt-0">
          {help}
        </FieldDescription>
      ) : null}
      <FieldError id={errorId} size="sm">
        {error}
      </FieldError>
    </>
  );

  if (layout === "group") {
    return (
      <fieldset
        className={cn("m-0 min-w-0 space-y-2 border-0 p-0", className)}
        aria-describedby={control["aria-describedby"]}
      >
        <legend className="p-0">{labelNode}</legend>
        {body}
        {messages}
      </fieldset>
    );
  }

  return (
    <Field className={cn("gap-2", className)}>
      {layout === "inline" ? (
        // Radix Switch renders a <button>, so a wrapping <label> would not
        // associate it; the id/htmlFor pair does.
        <div className="flex items-center gap-3">
          {body}
          {labelNode}
        </div>
      ) : (
        <>
          {labelNode}
          {body}
        </>
      )}
      {messages}
    </Field>
  );
}
