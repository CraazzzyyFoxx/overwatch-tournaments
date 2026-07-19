"use client";

import { useEffect, useState } from "react";
import type { BuiltInFieldConfig } from "@/types/registration.types";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";
import {
  getBuiltInValueValidationError,
  normalizeBuiltInFieldValue,
} from "./validation";
import FieldLabel from "./FieldLabel";

interface SmurfTagsInputProps {
  tags: string[];
  onChange: (tags: string[]) => void;
  suggestions: string[];
  label?: string;
  icon?: string;
  required?: boolean;
  config?: BuiltInFieldConfig;
  onValidationChange?: (error: string | null) => void;
}

export default function SmurfTagsInput({
  tags,
  onChange,
  suggestions,
  label,
  icon,
  required = false,
  config,
  onValidationChange,
}: SmurfTagsInputProps) {
  const t = useTranslations();
  const [inputValue, setInputValue] = useState("");
  const trimmedInputValue = inputValue.trim();
  const normalizedInputValue = normalizeBuiltInFieldValue("smurf_tags", inputValue);
  const inputValidationError = trimmedInputValue
    ? getBuiltInValueValidationError("smurf_tags", inputValue, config, t)
    : null;

  useEffect(() => {
    onValidationChange?.(inputValidationError);
  }, [inputValidationError, onValidationChange]);

  const addTag = (tag: string, options?: { clearInput?: boolean }) => {
    const normalized = normalizeBuiltInFieldValue("smurf_tags", tag);
    const validationError = getBuiltInValueValidationError("smurf_tags", tag, config);
    if (!normalized || validationError || tags.includes(normalized)) return;
    onChange([...tags, normalized]);
    if (options?.clearInput ?? true) {
      setInputValue("");
    }
  };

  const removeTag = (index: number) => {
    onChange(tags.filter((_, i) => i !== index));
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addTag(inputValue, { clearInput: true });
    }
    if (e.key === "Backspace" && !inputValue && tags.length > 0) {
      removeTag(tags.length - 1);
    }
  };

  const unusedSuggestions = suggestions.filter((s) => !tags.includes(s));

  return (
    <div className="space-y-1.5">
      <FieldLabel
        label={label ?? t("registration.accounts.smurfs")}
        required={required}
        icon={
          icon
            ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={icon} alt="" className="size-3.5 object-contain opacity-50" />
              )
            : undefined
        }
      />
      {tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {tags.map((tag, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 rounded-md border border-[color:var(--aqt-border-2)] bg-white/5 px-2 py-0.5 text-xs text-[color:var(--aqt-fg-muted)]"
            >
              {tag}
              <button
                type="button"
                onClick={() => removeTag(i)}
                className="ml-0.5 text-[color:var(--aqt-fg-dim)] hover:text-[color:var(--aqt-fg-muted)]"
              >
                &times;
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="relative">
        <input
          type="text"
          placeholder={t("registration.accounts.addSmurfPlaceholder")}
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          aria-invalid={Boolean(inputValidationError)}
          className={cn(
            "h-9 w-full rounded-lg border border-[color:var(--aqt-border-2)] bg-white/3 px-3 pr-16 text-sm text-[color:var(--aqt-fg)] placeholder-white/30 outline-none transition-colors focus:border-[color:var(--aqt-border-2)]",
            inputValidationError && "border-red-500/70 text-red-100 placeholder:text-red-200/60 focus:border-red-500/70",
          )}
        />
        <button
          type="button"
          onClick={() => addTag(inputValue, { clearInput: true })}
          disabled={!trimmedInputValue || Boolean(inputValidationError) || tags.includes(normalizedInputValue)}
          className="absolute right-1 top-1/2 h-7 -translate-y-1/2 rounded-md border border-[color:var(--aqt-border-2)] bg-white/6 px-2.5 text-xs font-medium text-[color:var(--aqt-fg)] transition-colors hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {t("registration.accounts.addSmurfButton")}
        </button>
      </div>
      {inputValidationError && (
        <p className="text-xs text-red-400">{inputValidationError}</p>
      )}
      {unusedSuggestions.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {unusedSuggestions.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => addTag(s, { clearInput: false })}
              className="rounded border border-[color:var(--aqt-border)] bg-white/2 px-2 py-0.5 text-[11px] text-[color:var(--aqt-fg-dim)] transition-colors hover:bg-white/5 hover:text-[color:var(--aqt-fg-muted)]"
            >
              + {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
