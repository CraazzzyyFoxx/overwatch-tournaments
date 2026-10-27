"use client";

import { useTranslations } from "next-intl";
import { ChevronDown, ChevronUp, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Combobox, ComboboxCheck } from "@/components/ui/combobox";
import { CommandGroup, CommandItem } from "@/components/ui/command";

interface HeaderMultiComboboxProps {
  /** Available header keys to choose from. */
  options: string[];
  /** Ordered list of selected header keys (order is significant). */
  value: string[];
  onChange: (value: string[]) => void;
  disabled?: boolean;
}

function moveItem(list: string[], index: number, direction: -1 | 1): string[] {
  const target = index + direction;
  if (target < 0 || target >= list.length) {
    return list;
  }
  const next = [...list];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

/** Multi-select combobox with selected chips that can be reordered/removed. */
export function HeaderMultiCombobox({ options, value, onChange, disabled }: Readonly<HeaderMultiComboboxProps>) {
  const t = useTranslations("sheetsFeed.controls");

  const toggle = (option: string) => {
    onChange(value.includes(option) ? value.filter((item) => item !== option) : [...value, option]);
  };

  return (
    <div className="space-y-2">
      {/* Uncontrolled: the popover stays open while columns are toggled. */}
      <Combobox
        label={value.length > 0 ? t("columnsSelected", { count: value.length }) : undefined}
        placeholder={t("selectColumns")}
        disabled={disabled || options.length === 0}
        searchPlaceholder={t("searchColumns")}
        emptyMessage={t("noColumns")}
      >
        <CommandGroup>
          {options.map((option) => (
            <CommandItem key={option} value={option} onSelect={() => toggle(option)}>
              <span className="min-w-0 flex-1 truncate">{option}</span>
              <ComboboxCheck selected={value.includes(option)} />
            </CommandItem>
          ))}
        </CommandGroup>
      </Combobox>

      {value.length > 0 ? (
        <ul className="flex flex-col gap-1.5">
          {value.map((column, index) => (
            <li
              key={column}
              className="flex items-center gap-1.5 rounded-md border border-border/60 bg-background/60 py-1 pl-2.5 pr-1 text-xs"
            >
              <span className="mr-auto truncate font-medium" title={column}>
                <span className="mr-1.5 text-muted-foreground">{index + 1}.</span>
                {column}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                disabled={disabled || index === 0}
                onClick={() => onChange(moveItem(value, index, -1))}
                title={t("moveUp")}
                className="text-muted-foreground"
              >
                <ChevronUp />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                disabled={disabled || index === value.length - 1}
                onClick={() => onChange(moveItem(value, index, 1))}
                title={t("moveDown")}
                className="text-muted-foreground"
              >
                <ChevronDown />
              </Button>
              <Button
                type="button"
                variant="ghost-destructive"
                size="icon-xs"
                disabled={disabled}
                onClick={() => onChange(value.filter((item) => item !== column))}
                title={t("remove")}
              >
                <X />
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
