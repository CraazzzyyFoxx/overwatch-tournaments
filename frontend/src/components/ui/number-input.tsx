"use client";

import * as React from "react";
import { useEffect, useState } from "react";

import { Input } from "@/components/ui/input";

export interface NumberInputProps
  extends Omit<React.ComponentProps<typeof Input>, "value" | "onChange" | "type" | "inputMode"> {
  /** Current numeric value; null/undefined renders an empty field. */
  value: number | null | undefined;
  /** Fires with a finite number while typing/committing, or null when the field is emptied. */
  onValueChange: (value: number | null) => void;
  min?: number;
  max?: number;
  /** Restrict to whole numbers (blocks the decimal point, rounds on commit). */
  integer?: boolean;
}

function clampNumber(
  value: number,
  min: number | undefined,
  max: number | undefined,
  integer: boolean
): number {
  let next = integer ? Math.round(value) : value;
  if (typeof min === "number" && next < min) {
    next = min;
  }
  if (typeof max === "number" && next > max) {
    next = max;
  }
  return next;
}

function toRawValue(value: number | null | undefined): string {
  return value === undefined || value === null ? "" : String(value);
}

/**
 * Text-based numeric input with draft state: free typing (comma tolerated as a
 * decimal point), invalid characters rejected, and min/max clamping applied on
 * blur. Extracted from the balancer settings sheet.
 */
const NumberInput = React.forwardRef<HTMLInputElement, NumberInputProps>(
  ({ value, onValueChange, min, max, integer = false, onFocus, onBlur, ...props }, ref) => {
    const [rawValue, setRawValue] = useState(() => toRawValue(value));
    const [isFocused, setIsFocused] = useState(false);

    /* eslint-disable react-hooks/set-state-in-effect -- Keep the editable string in sync with external value changes while preserving in-progress typing. */
    useEffect(() => {
      if (!isFocused) {
        setRawValue(toRawValue(value));
      }
    }, [isFocused, value]);
    /* eslint-enable react-hooks/set-state-in-effect */

    const sign = min === undefined || min < 0 ? "-?" : "";
    const pattern = integer
      ? new RegExp(`^${sign}\\d*$`)
      : new RegExp(`^${sign}\\d*(?:\\.\\d*)?$`);

    const handleChange = (nextRawValue: string) => {
      const normalized = nextRawValue.replace(",", ".");
      if (!pattern.test(normalized)) {
        return;
      }

      setRawValue(normalized);

      if (normalized === "") {
        onValueChange(null);
        return;
      }

      const parsed = Number(normalized);
      if (Number.isFinite(parsed)) {
        onValueChange(parsed);
      }
    };

    const handleBlur = (event: React.FocusEvent<HTMLInputElement>) => {
      setIsFocused(false);
      if (rawValue === "") {
        onValueChange(null);
        onBlur?.(event);
        return;
      }

      const parsed = Number(rawValue);
      if (!Number.isFinite(parsed)) {
        // Abandoned partial input ("-", "."): revert to the last committed value.
        setRawValue(toRawValue(value));
        onBlur?.(event);
        return;
      }

      const clamped = clampNumber(parsed, min, max, integer);
      setRawValue(String(clamped));
      onValueChange(clamped);
      onBlur?.(event);
    };

    return (
      <Input
        {...props}
        ref={ref}
        value={rawValue}
        type="text"
        inputMode={integer ? "numeric" : "decimal"}
        onFocus={(event) => {
          setIsFocused(true);
          onFocus?.(event);
        }}
        onBlur={handleBlur}
        onChange={(event) => handleChange(event.target.value)}
      />
    );
  }
);
NumberInput.displayName = "NumberInput";

export { NumberInput };
