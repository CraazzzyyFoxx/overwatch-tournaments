"use client";

import { useId, useState } from "react";
import { X } from "lucide-react";
import type { FormField as FormFieldSchema } from "@/types/forms.types";
import { useTranslations } from "next-intl";
import { SocialIcon } from "@/components/social/SocialIcon";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { normalizeAnswerText, validateAnswer } from "@/lib/forms/validate";
import FormField from "@/components/forms/FormField";

interface ExtraHandlesInputProps {
  /** The handles BESIDE the primary one, in order. */
  handles: string[];
  onChange: (handles: string[]) => void;
  /** How many extras the field's `max_count` still allows. */
  max: number;
  suggestions: string[];
  label?: string;
  /** The identity provider whose brand icon labels the field. */
  provider?: string;
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
  provider,
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
          provider ? (
            <SocialIcon provider={provider} size={14} decorative className="size-3.5 object-contain opacity-50" />
          ) : undefined
        }
        beforeControl={
          handles.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {handles.map((handle, i) => (
                <span
                  key={handle}
                  className="inline-flex items-center gap-1 rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] pl-2 pr-0.5 text-xs text-[color:var(--aqt-fg-muted)]"
                >
                  {handle}
                  <Button
                    type="button"
                    variant="ghost-destructive"
                    size="icon-xs"
                    onClick={() => removeHandle(i)}
                    aria-label={t("registration.accounts.removeSmurf", { tag: handle })}
                  >
                    <X aria-hidden />
                  </Button>
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
          <Button
            type="button"
            variant="outline"
            size="xs"
            onClick={() => addHandle(inputValue, { clearInput: true })}
            disabled={
              full ||
              !trimmedInputValue ||
              Boolean(inputValidationError) ||
              handles.includes(normalizedInputValue)
            }
            className="absolute right-1 top-1/2 -translate-y-1/2"
          >
            {t("registration.accounts.addSmurfButton")}
          </Button>
        }
      />
      {unusedSuggestions.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {unusedSuggestions.map((s) => (
            <Button
              key={s}
              type="button"
              variant="dashed"
              size="xs"
              onClick={() => addHandle(s, { clearInput: false })}
            >
              + {s}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
