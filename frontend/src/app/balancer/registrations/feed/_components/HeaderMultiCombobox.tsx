"use client";

import { useState } from "react";
import { Check, ChevronDown, ChevronsUpDown, ChevronUp, X } from "lucide-react";

import { Button } from "@/components/ui/button";
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
export function HeaderMultiCombobox({ options, value, onChange, disabled }: HeaderMultiComboboxProps) {
  const [open, setOpen] = useState(false);

  const toggle = (option: string) => {
    onChange(value.includes(option) ? value.filter((item) => item !== option) : [...value, option]);
  };

  return (
    <div className="space-y-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            role="combobox"
            aria-expanded={open}
            disabled={disabled || options.length === 0}
            className="h-9 w-full justify-between font-normal"
          >
            <span className={cn("truncate", value.length === 0 && "text-muted-foreground")}>
              {value.length > 0 ? `${value.length} column${value.length === 1 ? "" : "s"} selected` : "Select columns…"}
            </span>
            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="p-0" style={{ width: "var(--radix-popover-trigger-width)" }}>
          <Command>
            <CommandInput placeholder="Search columns…" />
            <CommandList>
              <CommandEmpty>No columns found.</CommandEmpty>
              <CommandGroup>
                {options.map((option) => {
                  const checked = value.includes(option);
                  return (
                    <CommandItem key={option} value={option} onSelect={() => toggle(option)}>
                      <Check className={cn("mr-2 h-4 w-4", checked ? "opacity-100" : "opacity-0")} />
                      <span className="truncate">{option}</span>
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>

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
              <button
                type="button"
                disabled={disabled || index === 0}
                onClick={() => onChange(moveItem(value, index, -1))}
                title="Move up"
                className="rounded p-0.5 text-muted-foreground transition-colors hover:bg-accent disabled:opacity-30"
              >
                <ChevronUp className="size-3.5" />
              </button>
              <button
                type="button"
                disabled={disabled || index === value.length - 1}
                onClick={() => onChange(moveItem(value, index, 1))}
                title="Move down"
                className="rounded p-0.5 text-muted-foreground transition-colors hover:bg-accent disabled:opacity-30"
              >
                <ChevronDown className="size-3.5" />
              </button>
              <button
                type="button"
                disabled={disabled}
                onClick={() => onChange(value.filter((item) => item !== column))}
                title="Remove"
                className="rounded p-0.5 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive disabled:opacity-30"
              >
                <X className="size-3.5" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
