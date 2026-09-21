"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";
import { useTranslations } from "next-intl";
import type { FormField } from "@/types/forms.types";

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { normalizeAnswerText, validateAnswer } from "@/lib/forms/validate";
import { Input } from "@/components/ui/input";
import FieldLabel from "./FieldLabel";
import { fieldControlClass, fieldInvalidClass } from "./FormField";

interface AccountComboboxProps {
  label: string;
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
  suggestions: string[];
  icon?: string;
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
  icon,
  required = false,
  field,
  error = null,
}: Readonly<AccountComboboxProps>) {
  const t = useTranslations();
  const tErrors = useTranslations("forms.errors");
  const [open, setOpen] = useState(false);
  const [inputValue, setInputValue] = useState(value);
  const [contentWidth, setContentWidth] = useState<number>();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listboxId = useId();
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

  useEffect(() => {
    setInputValue(value);
  }, [value]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const nextWidth = triggerRef.current?.offsetWidth;
    if (nextWidth) {
      setContentWidth(nextWidth);
    }
  }, [open]);

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

  const iconEl = icon ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={icon} alt="" className="size-3.5 object-contain opacity-50" />
  ) : null;

  return (
    <div className="space-y-2">
      <FieldLabel label={label} htmlFor={controlId} required={required} icon={iconEl} />
      {hasSuggestions ? (
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <button
              ref={triggerRef}
              id={controlId}
              type="button"
              role="combobox"
              aria-controls={listboxId}
              aria-expanded={open}
              aria-invalid={Boolean(shownError)}
              aria-describedby={shownError ? errorId : undefined}
              className={cn(
                fieldControlClass,
                "flex h-9 items-center justify-between",
                value ? "text-[color:var(--aqt-fg)]" : "text-[color:var(--aqt-fg-dim)]",
                shownError && fieldInvalidClass,
              )}
            >
              <span className="truncate">{value || placeholder}</span>
              <ChevronsUpDown className="ml-2 size-3.5 shrink-0 text-[color:var(--aqt-fg-dim)]" aria-hidden />
            </button>
          </PopoverTrigger>
          <PopoverContent
            id={listboxId}
            align="start"
            className="p-0"
            style={{ width: contentWidth }}
          >
            <Command>
              <CommandInput
                value={inputValue}
                onValueChange={handleInputChange}
                placeholder={placeholder}
              />
              <CommandList>
                <CommandEmpty>
                  {inputValue
                    ? t("registration.accounts.typeToUseCustom")
                    : t("registration.accounts.noLinkedAccounts")}
                </CommandEmpty>
                <CommandGroup heading={t("registration.accounts.linkedAccounts")}>
                  {filtered.map((s) => (
                    <CommandItem key={s} value={s} onSelect={() => handleSelect(s)}>
                      <span className="flex-1 truncate">{s}</span>
                      <Check className={cn("ml-2 size-4", value === s ? "opacity-100" : "opacity-0")} aria-hidden />
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
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>
      ) : (
        <Input
          id={controlId}
          type="text"
          placeholder={placeholder}
          value={inputValue}
          onChange={(e) => handleInputChange(e.target.value)}
          aria-invalid={Boolean(shownError)}
          aria-describedby={shownError ? errorId : undefined}
          className={cn(fieldControlClass, "h-9", shownError && fieldInvalidClass)}
        />
      )}
      {shownError && (
        <p id={errorId} className="text-xs text-destructive">{shownError}</p>
      )}
    </div>
  );
}
