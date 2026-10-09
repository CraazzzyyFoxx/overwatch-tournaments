"use client";

import { useId, useState } from "react";
import { X } from "lucide-react";
import type { FormField as FormFieldSchema } from "@/types/forms.types";
import { useTranslations } from "next-intl";
import { normalizeAnswerText, validateAnswer } from "@/lib/forms/validate";
import FormField from "./FormField";

interface ExtraHandlesInputProps {
  /** The handles BESIDE the primary one, in order. */
  handles: string[];
  onChange: (handles: string[]) => void;
  /** How many extras the field's `max_count` still allows. */
  max: number;
  suggestions: string[];
  label?: string;
  icon?: string;
  /** The schema field these handles answer; drives the per-handle format check. */
  field?: FormFieldSchema;
}

/**
 * The extra handles of an identity answer — a BattleTag's smurfs, in practice.
 *
 * One chip per stored handle, one box for the next: the field's pattern
 * describes a SINGLE handle, so each one is checked on its own before it joins
 * the list. The primary handle is the parent's business; this control never
 * sees it.
 */
export default function ExtraHandlesInput({
  handles,
  onChange,
  max,
  suggestions,
  label,
  icon,
  field,
}: Readonly<ExtraHandlesInputProps>) {
  const t = useTranslations();
  const tErrors = useTranslations("forms.errors");
  const inputId = useId();
  const [inputValue, setInputValue] = useState("");
  const trimmedInputValue = inputValue.trim();
  /** Canonical form of the pending handle, or the raw text when this control is
   *  not bound to a field (nothing to normalize against). */
  const normalize = (handle: string): string =>
    field ? normalizeAnswerText(field, handle) : handle.trim();
  const normalizedInputValue = normalize(inputValue);
  const full = handles.length >= max;

  /** One handle at a time: the pending box is not yet part of the stored list,
   *  so the list-level rules (the ceiling, duplicates) are checked here. */
  const handleError = (handle: string): string | null =>
    field && handle.trim() ? validateAnswer(field, handle, tErrors) : null;

  const inputValidationError = handleError(inputValue);

  const addHandle = (handle: string, options?: { clearInput?: boolean }) => {
    const normalized = normalize(handle);
    if (!normalized || full || handleError(handle) || handles.includes(normalized)) return;
    onChange([...handles, normalized]);
    if (options?.clearInput ?? true) {
      setInputValue("");
    }
  };

  const removeHandle = (index: number) => {
    onChange(handles.filter((_, i) => i !== index));
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addHandle(inputValue, { clearInput: true });
    }
    if (e.key === "Backspace" && !inputValue && handles.length > 0) {
      removeHandle(handles.length - 1);
    }
  };

  const unusedSuggestions = full ? [] : suggestions.filter((s) => !handles.includes(s));

  return (
    <div className="space-y-1.5">
      <FormField
        id={inputId}
        label={label ?? t("registration.accounts.smurfs")}
        icon={
          icon
            ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={icon} alt="" className="size-3.5 object-contain opacity-50" />
              )
            : undefined
        }
        beforeControl={
          handles.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {handles.map((handle, i) => (
                <span
                  key={handle}
                  className="inline-flex items-center gap-1 rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] px-2 py-0.5 text-xs text-[color:var(--aqt-fg-muted)]"
                >
                  {handle}
                  <button
                    type="button"
                    onClick={() => removeHandle(i)}
                    aria-label={t("registration.accounts.removeSmurf", { tag: handle })}
                    className="ml-0.5 rounded text-[color:var(--aqt-fg-dim)] transition-colors hover:text-[color:var(--aqt-fg-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <X className="size-3" aria-hidden />
                  </button>
                </span>
              ))}
            </div>
          ) : null
        }
        placeholder={t("registration.accounts.addSmurfPlaceholder")}
        value={inputValue}
        onChange={setInputValue}
        onKeyDown={handleKeyDown}
        disabled={full}
        error={inputValidationError}
        className="pr-16"
        endAdornment={
          <button
            type="button"
            onClick={() => addHandle(inputValue, { clearInput: true })}
            disabled={
              full ||
              !trimmedInputValue ||
              Boolean(inputValidationError) ||
              handles.includes(normalizedInputValue)
            }
            className="absolute right-1 top-1/2 h-7 -translate-y-1/2 rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] px-2.5 text-xs font-medium text-[color:var(--aqt-fg)] transition-colors hover:bg-[color:var(--aqt-overlay-3)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-40"
          >
            {t("registration.accounts.addSmurfButton")}
          </button>
        }
      />
      {unusedSuggestions.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {unusedSuggestions.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => addHandle(s, { clearInput: false })}
              className="rounded border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-2 py-0.5 text-label text-[color:var(--aqt-fg-dim)] transition-colors hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              + {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
