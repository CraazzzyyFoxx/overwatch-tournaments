"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import type { FormField } from "@/types/forms.types";

import FieldLabel from "@/components/forms/FieldLabel";
import { SocialIcon } from "@/components/social/SocialIcon";
import { Combobox, ComboboxCheck } from "@/components/ui/combobox";
import { CommandGroup, CommandItem } from "@/components/ui/command";
import { FieldError } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { normalizeAnswerText, validateAnswer } from "@/lib/forms/validate";

interface AccountComboboxProps {
  label: string;
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
  suggestions: string[];
  /** Social provider whose brand icon leads the label. */
  provider?: string;
  required?: boolean;
  /** The schema field this control answers. Drives the live format check and
   *  the canonical form of what is stored. */
  field?: FormField;
  /** Error owned by the form: a server rejection, or a revealed step objection. */
  error?: string | null;
}

export default function AccountCombobox({
  label,
  placeholder,
  value,
  onChange,
  suggestions,
  provider,
  required = false,
  field,
  error = null,
}: Readonly<AccountComboboxProps>) {
  const t = useTranslations();
  const tErrors = useTranslations("forms.errors");
  const [open, setOpen] = useState(false);
  const [inputValue, setInputValue] = useState(value);
  const controlId = useId();
  const errorId = `${controlId}-error`;

  /** Format only: an empty box is the step's business, not this control's. */
  const formatError = (candidate: string): string | null =>
    field && candidate.trim() ? validateAnswer(field, candidate, tErrors) : null;

  const normalize = (candidate: string): string =>
    field ? normalizeAnswerText(field, candidate) : candidate.trim();

  const liveError = formatError(inputValue);
  const shownError = error ?? liveError;
  const normalizedInputValue = normalize(inputValue);

  // A new answer from the form (a pick, a reset) replaces what the box shows.
  // Adjusted during render, so the stale text is never painted first.
  const [syncedValue, setSyncedValue] = useState(value);
  if (value !== syncedValue) {
    setSyncedValue(value);
    setInputValue(value);
  }

  const handleSelect = (selected: string) => {
    if (formatError(selected)) {
      setInputValue(selected);
      return;
    }
    const nextValue = normalize(selected);
    onChange(nextValue);
    setInputValue(nextValue);
    setOpen(false);
  };

  const handleInputChange = (v: string) => {
    setInputValue(v);
    if (!v.trim()) {
      onChange("");
      return;
    }
    // A half-typed BattleTag must not be pushed up as the answer; the box keeps
    // it locally until it is a shape the field accepts.
    if (!formatError(v)) {
      onChange(normalize(v));
    }
  };

  const hasSuggestions = suggestions.length > 0;
  const filtered = inputValue
    ? suggestions.filter((s) => s.toLowerCase().includes(inputValue.toLowerCase()))
    : suggestions;

  const iconEl = provider ? (
    <SocialIcon provider={provider} size={14} className="size-3.5 object-contain opacity-50" decorative />
  ) : null;

  return (
    <div className="space-y-2">
      <FieldLabel label={label} htmlFor={controlId} required={required} icon={iconEl} />
      {hasSuggestions ? (
        <Combobox
          id={controlId}
          open={open}
          onOpenChange={setOpen}
          label={value}
          placeholder={placeholder}
          variant="surface"
          aria-invalid={Boolean(shownError)}
          aria-describedby={shownError ? errorId : undefined}
          searchValue={inputValue}
          onSearchValueChange={handleInputChange}
          searchPlaceholder={placeholder}
          emptyMessage={
            inputValue
              ? t("registration.accounts.typeToUseCustom")
              : t("registration.accounts.noLinkedAccounts")
          }
        >
          <CommandGroup heading={t("registration.accounts.linkedAccounts")}>
            {filtered.map((s) => (
              <CommandItem key={s} value={s} onSelect={() => handleSelect(s)}>
                <span className="min-w-0 flex-1 truncate">{s}</span>
                <ComboboxCheck selected={value === s} />
              </CommandItem>
            ))}
          </CommandGroup>
          {inputValue && !suggestions.includes(inputValue) && !liveError && (
            <CommandGroup heading={t("registration.accounts.custom")}>
              <CommandItem value={normalizedInputValue} onSelect={() => handleSelect(inputValue)}>
                {t("registration.accounts.useValue", { value: normalizedInputValue })}
              </CommandItem>
            </CommandGroup>
          )}
        </Combobox>
      ) : (
        <Input
          id={controlId}
          type="text"
          placeholder={placeholder}
          value={inputValue}
          onChange={(e) => handleInputChange(e.target.value)}
          aria-invalid={Boolean(shownError)}
          aria-describedby={shownError ? errorId : undefined}
        />
      )}
      <FieldError id={errorId} size="sm">
        {shownError}
      </FieldError>
    </div>
  );
}
