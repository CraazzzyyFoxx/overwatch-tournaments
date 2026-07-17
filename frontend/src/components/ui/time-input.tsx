"use client";

import * as React from "react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const COMPLETE_TIME = /^\d{1,2}:\d{2}$/;

function normalizeTime(value: string): string | null {
  const raw = value.trim();
  if (!raw) return "";

  let hours: number;
  let minutes: number;

  if (raw.includes(":")) {
    const match = /^(\d{1,2}):(\d{1,2})$/.exec(raw);
    if (!match) return null;
    hours = Number(match[1]);
    minutes = Number(match[2]);
  } else {
    const digits = raw.replace(/\D/g, "");
    if (digits.length <= 2) {
      hours = Number(digits);
      minutes = 0;
    } else if (digits.length === 3) {
      hours = Number(digits.slice(0, 1));
      minutes = Number(digits.slice(1));
    } else if (digits.length === 4) {
      hours = Number(digits.slice(0, 2));
      minutes = Number(digits.slice(2));
    } else {
      return null;
    }
  }

  if (!Number.isInteger(hours) || hours > 23 || minutes > 59) return null;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

interface TimeInputProps
  extends Omit<React.ComponentProps<typeof Input>, "onChange" | "type" | "value"> {
  value?: string | null;
  onValueChange: (value: string) => void;
}

const TimeInput = React.forwardRef<HTMLInputElement, TimeInputProps>(
  ({ className, onBlur, onValueChange, value, ...props }, ref) => {
    const controlledValue = value ?? "";
    const [draft, setDraft] = React.useState(controlledValue);

    React.useEffect(() => setDraft(controlledValue), [controlledValue]);

    const normalizedDraft = normalizeTime(draft);
    const isInvalid = COMPLETE_TIME.test(draft) && normalizedDraft === null;

    return (
      <Input
        {...props}
        ref={ref}
        type="text"
        inputMode="numeric"
        autoComplete="off"
        spellCheck={false}
        maxLength={5}
        pattern="[0-2]?[0-9]:[0-5][0-9]"
        placeholder="HH:MM"
        value={draft}
        aria-invalid={props["aria-invalid"] || isInvalid || undefined}
        className={cn("tabular-nums", className)}
        onChange={(event) => {
          const nextDraft = event.target.value.replace(/[^\d:]/g, "").slice(0, 5);
          setDraft(nextDraft);

          if (COMPLETE_TIME.test(nextDraft)) {
            const normalized = normalizeTime(nextDraft);
            if (normalized !== null) onValueChange(normalized);
          } else if (!nextDraft) {
            onValueChange("");
          }
        }}
        onBlur={(event) => {
          const normalized = normalizeTime(draft);
          if (normalized === null) {
            setDraft(controlledValue);
          } else {
            setDraft(normalized);
            if (normalized !== controlledValue) onValueChange(normalized);
          }
          onBlur?.(event);
        }}
      />
    );
  }
);
TimeInput.displayName = "TimeInput";

export { TimeInput, type TimeInputProps };
