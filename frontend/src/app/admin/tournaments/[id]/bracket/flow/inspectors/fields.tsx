"use client";

import { useId, type ReactNode } from "react";

import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@craazzzyyfoxx/admin-kit/ui/select";

/** A labelled field row: the label points at the control through `htmlFor`. */
export function Field({ label, children }: Readonly<{ label: string; children: (id: string) => ReactNode }>) {
  const id = useId();
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children(id)}
    </div>
  );
}

export function SelectField({
  label,
  value,
  options,
  onChange,
  disabled
}: Readonly<{
  label: string;
  value: string;
  options: readonly (readonly [value: string, label: string])[];
  onChange: (value: string) => void;
  disabled?: boolean;
}>) {
  return (
    <Field label={label}>
      {(id) => (
        <Select value={value} onValueChange={onChange} disabled={disabled}>
          <SelectTrigger id={id}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {options.map(([optionValue, optionLabel]) => (
              <SelectItem key={optionValue} value={optionValue}>
                {optionLabel}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    </Field>
  );
}

export function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  disabled
}: Readonly<{
  label: string;
  value: number | null;
  onChange: (value: number | null) => void;
  min?: number;
  max?: number;
  disabled?: boolean;
}>) {
  return (
    <Field label={label}>
      {(id) => <NumberInput id={id} integer min={min} max={max} value={value} onValueChange={onChange} disabled={disabled} />}
    </Field>
  );
}
