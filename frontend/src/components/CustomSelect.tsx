"use client";

import React, { useEffect, useMemo } from "react";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandList
} from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { CaretSortIcon } from "@radix-ui/react-icons";

export interface CustomSelectItem {
  value: any;
  label: string;
  item?: React.ReactNode;
}

export interface CustomSelectProps {
  items: CustomSelectItem[];
  placeholder?: string;
  value: any;
  onSelect: (value: any) => void;
  className?: string;
}

const CustomSelect = ({ items, placeholder, value, onSelect, className }: CustomSelectProps) => {
  const [isOpen, setIsOpen] = React.useState<boolean>(false);

  const selectedItem: string | undefined = useMemo(() => {
    const item = items.find((item) => item.value == value);
    if (!item) return undefined;
    return item.label;
  }, [items, value]);

  const [prevValue, setPrevValue] = React.useState(value);

  if (value !== prevValue) {
    setPrevValue(value);
    if (isOpen) setIsOpen(false);
  }

  return (
    <div
      onFocus={() => setIsOpen(true)}
      onClick={() => setIsOpen(true)}
      className={cn("relative", className)}
    >
      <Popover open={isOpen} onOpenChange={setIsOpen}>
        <PopoverAnchor asChild>
          <div>
            <Input
              value={selectedItem ?? ""}
              onFocus={() => setIsOpen(true)}
              onClick={() => setIsOpen(true)}
              onChange={() => {}}
              placeholder={placeholder}
              className={cn("pr-8", className)}
            />
            <CaretSortIcon className="absolute right-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          </div>
        </PopoverAnchor>
        <PopoverContent
          className="p-0 w-auto"
          onOpenAutoFocus={(e) => e.preventDefault()}
          style={{ minWidth: "var(--radix-popover-trigger-width)" }}
        >
          <Command className="rounded-lg border shadow-md w-full">
            <CommandList>
              <CommandEmpty>No results found.</CommandEmpty>
              <CommandGroup>
                {items.map((item) => (
                  <CommandItem
                    key={item.value}
                    onSelect={() => {
                      onSelect(item.value);
                    }}
                  >
                    {item.item || item.label}
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
};

export default CustomSelect;
