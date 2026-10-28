"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Combobox, ComboboxCheck } from "@/components/ui/combobox";
import { CommandGroup, CommandItem } from "@/components/ui/command";

interface HeaderComboboxProps {
  /** Available header keys to choose from. */
  options: string[];
  value: string | null;
  onChange: (value: string | null) => void;
  disabled?: boolean;
  placeholder?: string;
}

/** Single-select combobox over deduped sheet header keys. */
export function HeaderCombobox({
  options,
  value,
  onChange,
  disabled,
  placeholder,
}: Readonly<HeaderComboboxProps>) {
  const t = useTranslations("sheetsFeed.controls");
  const resolvedPlaceholder = placeholder ?? t("selectColumn");
  const [open, setOpen] = useState(false);
  const pick = (next: string | null) => {
    onChange(next);
    setOpen(false);
  };

  return (
    <Combobox
      open={open}
      onOpenChange={setOpen}
      label={value}
      placeholder={resolvedPlaceholder}
      disabled={disabled || options.length === 0}
      searchPlaceholder={t("searchColumns")}
      emptyMessage={t("noColumns")}
      clear={value ? { label: t("clearSelection"), value: "__clear__", onSelect: () => pick(null) } : undefined}
    >
      <CommandGroup>
        {options.map((option) => (
          <CommandItem key={option} value={option} onSelect={() => pick(option === value ? null : option)}>
            <span className="min-w-0 flex-1 truncate">{option}</span>
            <ComboboxCheck selected={option === value} />
          </CommandItem>
        ))}
      </CommandGroup>
    </Combobox>
  );
}
