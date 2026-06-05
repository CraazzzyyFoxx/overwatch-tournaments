"use client";

import React, { useEffect, useRef, useState } from "react";
import Image from "next/image";
import { Check, ChevronsUpDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export interface SearchableImageOption {
  value: string;
  label: string;
  imageSrc?: string | null;
}

interface SearchableImageSelectProps {
  /** Currently selected value, or undefined when "all" / cleared. */
  value?: string;
  /** Called with the new value, or undefined when cleared. */
  onValueChange: (nextValue: string | undefined) => void;
  /** Full list of selectable items. */
  options: SearchableImageOption[];
  /** Placeholder text shown when nothing is selected. Also used as the clear-option label. */
  placeholder: string;
  /** Placeholder for the search input inside the popover. */
  searchPlaceholder?: string;
  /** Whether the selector is in a loading state. */
  isLoading?: boolean;
  /** Whether the selector is disabled (loading or error). */
  disabled?: boolean;
}

const SearchableImageSelect = ({
  value,
  onValueChange,
  options,
  placeholder,
  searchPlaceholder = "Search...",
  isLoading = false,
  disabled = false,
}: SearchableImageSelectProps) => {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const [contentWidth, setContentWidth] = useState<number | undefined>(undefined);

  useEffect(() => {
    if (!open) return;
    setContentWidth(triggerRef.current?.offsetWidth);
  }, [open]);

  const selected = options.find((o) => o.value === value);

  const handleSelect = (nextValue: string | undefined) => {
    onValueChange(nextValue);
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          ref={triggerRef}
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          disabled={disabled}
          className="h-10 w-full justify-between border-border/60 bg-background/15 font-normal hover:bg-background/20"
        >
          <div className="flex items-center gap-2 overflow-hidden">
            {selected?.imageSrc ? (
              <img
                src={selected.imageSrc}
                alt={selected.label}
                className="h-5.5 w-5.5 shrink-0 object-contain select-none"
              />
            ) : null}
            {isLoading ? (
              <Skeleton className="h-4 w-28" />
            ) : (
              <span className="truncate">{selected ? selected.label : placeholder}</span>
            )}
          </div>
          <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="liquid-glass-panel p-0"
        style={contentWidth ? { width: `${contentWidth}px` } : undefined}
      >
        <Command className="liquid-glass-surface">
          <CommandInput placeholder={searchPlaceholder} />
          <CommandList>
            <CommandEmpty>No results found.</CommandEmpty>
            <CommandGroup>
              {/* Clear / "All" option */}
              <CommandItem
                value={`__clear__ ${placeholder}`}
                onSelect={() => handleSelect(undefined)}
              >
                <span>{placeholder}</span>
                <Check
                  className={`ml-auto h-4 w-4 ${value === undefined ? "opacity-100" : "opacity-0"}`}
                />
              </CommandItem>
              {options.map((option) => (
                <CommandItem
                  key={option.value}
                  value={`${option.label} ${option.value}`}
                  onSelect={() => handleSelect(option.value)}
                >
                  <div className="flex items-center gap-2">
                    {option.imageSrc ? (
                      <img
                        src={option.imageSrc}
                        alt={option.label}
                        className="h-5 w-5 object-contain select-none"
                      />
                    ) : null}
                    <span>{option.label}</span>
                  </div>
                  <Check
                    className={`ml-auto h-4 w-4 ${value === option.value ? "opacity-100" : "opacity-0"}`}
                  />
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
};

export default SearchableImageSelect;
